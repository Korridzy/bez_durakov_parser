import * as T from "three";
import { RoomEnvironment } from "three/addons/environments/RoomEnvironment.js";
import { ShovelRotation } from "./shovel-rotation";
import { DIG_CYCLE, diggingPose, diggingEvents, dirtParticle } from "./digging";
import type { Activity } from "./Expedition";
import {
  createShovelModel,
  disposeModel,
  waveFlag,
  setMouthFrame,
  mouthFrame,
  placeScenery,
  fitShadowGround,
  rotateShovel,
  addGroundOcclusion,
  type ShovelAssets,
} from "./shovel-model";

export type SceneState = {
  activity: Activity;
  motion: boolean;
  visible: boolean;
  engaged: boolean;
  accent: string;
  speech?: string;
};
export type ShovelScene = ReturnType<typeof createShovelScene>;

export async function loadShovelAssets(): Promise<ShovelAssets> {
  const loader = new T.TextureLoader();
  const result = await Promise.allSettled([
    loader.loadAsync("/mascot/mouths.png"),
    loader.loadAsync("/mascot/island.png"),
  ]);
  if (result.some((item) => item.status === "rejected")) {
    result.forEach((item) => {
      if (item.status === "fulfilled") item.value.dispose();
    });
    throw new Error("Companion images could not be loaded");
  }
  const [mouths, island] = result.map(
    (item) => (item as PromiseFulfilledResult<T.Texture>).value,
  );
  for (const texture of [mouths, island]) {
    texture.colorSpace = T.SRGBColorSpace;
    texture.anisotropy = 4;
  }
  // Mipmaps can blend neighbouring atlas expressions at the small dock size.
  mouths.generateMipmaps = false;
  mouths.minFilter = T.LinearFilter;
  return { mouths, island };
}

export function createShovelScene(
  canvas: HTMLCanvasElement,
  initial: SceneState,
  onFailure: () => void,
  assets: ShovelAssets,
) {
  const renderer = new T.WebGLRenderer({
    canvas,
    alpha: true,
    antialias: true,
    powerPreference: "low-power",
  });
  renderer.setPixelRatio(2);
  renderer.setClearColor(0x000000, 0);
  renderer.outputColorSpace = T.SRGBColorSpace;
  renderer.toneMapping = T.ACESFilmicToneMapping;
  renderer.toneMappingExposure = 0.88;
  renderer.shadowMap.enabled = true;
  renderer.shadowMap.type = T.PCFShadowMap;
  renderer.localClippingEnabled = true;
  const scene = new T.Scene();
  const camera = new T.OrthographicCamera(-2.25, 2.25, 2, -2, 0.1, 40);
  camera.position.set(2.3, 4.4, 8);
  const target = new T.Vector3(0.13, 0.94, 0);
  camera.lookAt(target);
  camera.updateMatrixWorld();
  const azimuth = Math.atan2(
    camera.position.x - target.x,
    camera.position.z - target.z,
  );
  const rotation = new ShovelRotation();
  const environment = new RoomEnvironment();
  const pmrem = new T.PMREMGenerator(renderer);
  const environmentMap = pmrem.fromScene(environment, 0.04);
  scene.environment = environmentMap.texture;
  scene.environmentIntensity = 0.75;
  environment.dispose();
  pmrem.dispose();
  scene.add(new T.HemisphereLight("#fff7ec", "#9375b5", 0.65));
  const key = new T.DirectionalLight("#fff5e5", 2.0);
  key.position.set(
    -3 * Math.cos(azimuth) + 4 * Math.sin(azimuth),
    7,
    3 * Math.sin(azimuth) + 4 * Math.cos(azimuth),
  );
  key.castShadow = true;
  key.shadow.mapSize.set(1024, 1024);
  Object.assign(key.shadow.camera, {
    left: -3,
    right: 3,
    top: 4,
    bottom: -3,
    near: 0.5,
    far: 16,
  });
  key.shadow.normalBias = 0.035;
  key.shadow.bias = -0.00015;
  scene.add(key);
  const rim = new T.DirectionalLight("#d5c8ff", 1.5);
  rim.position.set(3, 3, -4);
  scene.add(rim);
  const model = createShovelModel(assets);
  scene.add(model.root);
  placeScenery(model.island, model.flagRig, camera, azimuth);
  fitShadowGround(model.ground, model.island, camera);
  addGroundOcclusion(model.root, model.ground, model.character);
  // Render the transparent painting first; it must never cover opaque geometry.
  const backdrop = new T.Scene();
  backdrop.add(model.island);
  renderer.autoClear = false;
  function render() {
    renderer.clear();
    renderer.render(backdrop, camera);
    renderer.render(scene, camera);
  }

  let state = initial,
    disposed = false,
    failed = false,
    frame = 0,
    last = 0,
    clock = 0;
  let manualUntil = 0,
    manual: "hello" | "dig" | "delight" = "hello",
    sequence = 0;
  let pointerX = 0,
    pointerY = 0,
    pointedUntil = 0;
  let pointerAt = 0;
  let nextBlink = 2.4,
    blinkAt = -10;
  let activitySince = 0;
  let digTime = 0,
    wasDigging = false,
    soilTarget = 0,
    soilAmount = 0,
    soilUntil = 0;
  const particleBirths = Array.from({ length: model.dust.length }, () => -100);
  let talkUntil = initial.speech
    ? Math.min(5, 1 + initial.speech.length * 0.045)
    : 0;
  const pose = {
    bounce: 0,
    tilt: -0.065,
    pitch: 0,
    smile: 1,
    brow: 0,
    gazeX: 0,
    gazeY: 0,
  };
  let facing = 0;
  const reduced = matchMedia("(prefers-reduced-motion: reduce)");
  const canAnimate = () => state.motion && !reduced.matches;
  const isVisible = () =>
    state.visible && document.visibilityState === "visible";
  function schedule() {
    if (!frame && !disposed && !failed && isVisible())
      frame = requestAnimationFrame(paint);
  }
  function paint(now: number) {
    frame = 0;
    if (disposed || failed || !isVisible()) return;
    const moving = canAnimate();
    const dt = last ? Math.min((now - last) / 1000, 0.05) : 1 / 30;
    if (moving && now - last < 32) {
      schedule();
      return;
    }
    last = now;
    if (moving) clock += dt;
    const t = clock;
    const activity =
      state.activity === "success" && t - activitySince > 4
        ? "rest"
        : state.activity;
    const action = moving && t < manualUntil ? manual : activity;
    const digging = action === "working" || action === "dig";
    const diggingNow = digging && moving && !rotation.held;
    if (digging && !wasDigging) digTime = 0;
    wasDigging = digging;
    if (diggingNow) {
      const before = digTime;
      digTime += dt;
      for (const event of diggingEvents(before, digTime)) {
        model.dust.forEach((_, i) => {
          if (i < 8 === (event.kind === "impact"))
            particleBirths[i] = clock - (digTime - event.time);
        });
        soilTarget = Math.min(
          1,
          soilTarget + (event.kind === "impact" ? 0.55 : 0.2),
        );
        if (event.kind === "impact") blinkAt = clock;
      }
      soilUntil = clock + 3;
    }
    const dig = diggingPose(digTime);
    const happy =
      action === "success" || action === "delight" || action === "hello";
    const thinking =
      action === "thinking" || (digging && dig.phase === "think");
    const worried = action === "error";
    const beat = Math.sin(t * (happy ? 4 : 1.8));
    const bounce =
      moving && !rotation.held
        ? happy
          ? Math.max(0, beat) * 0.19
          : diggingNow
            ? dig.height
            : Math.sin(t * 1.7) * 0.018
        : 0;
    const tilt = rotation.held
      ? 0
      : diggingNow
        ? dig.roll
        : (thinking ? 0.12 : worried ? -0.12 : -0.065) +
          (moving ? beat * 0.025 : 0);
    const front = state.engaged || thinking || digging;
    const looking = t < pointedUntil;
    const gazeX = front
      ? 0
      : looking
        ? pointerX * 0.043
        : moving
          ? Math.sin(t * 0.55) * 0.035
          : 0;
    const gazeY = thinking
      ? 0.036
      : front
        ? 0.014
        : looking
          ? pointerY * 0.04
          : thinking
            ? 0.034
            : 0;
    const target = {
      bounce,
      tilt,
      pitch: diggingNow ? dig.pitch : 0,
      smile: worried ? 0.3 : thinking ? 0.7 : happy ? 1.3 : 1,
      brow: worried ? -0.19 : thinking ? 0.18 : happy ? 0.07 : 0,
      gazeX,
      gazeY,
    };
    const amount = moving && !rotation.held ? 1 - Math.exp(-dt * 10) : 1;
    for (const key of Object.keys(pose) as (keyof typeof pose)[])
      pose[key] += (target[key] - pose[key]) * amount;
    if (diggingNow) {
      // The strike is deliberately sharp. Interpolating it like idle motion
      // would erase the impact and make the blade float through the ground.
      pose.bounce = dig.height;
      pose.pitch = dig.pitch;
      pose.tilt = dig.roll;
    }
    model.character.position.y = 0;
    model.characterPivot.position.y = model.ground.position.y + pose.bounce;
    const faceTarget =
      front && !rotation.oriented && !rotation.held ? azimuth : 0;
    const faceDelta =
      T.MathUtils.euclideanModulo(faceTarget - facing + Math.PI, Math.PI * 2) -
      Math.PI;
    facing += faceDelta * amount;
    model.character.rotation.set(pose.pitch, facing, pose.tilt);
    rotateShovel(model.characterPivot, rotation.yaw, rotation.pitch, azimuth);
    // Scale gently around the blade tip; no humanoid skeleton or bending limbs.
    if (diggingNow) model.character.scale.setScalar(1.08);
    else
      model.character.scale.set(
        1.08 - pose.bounce * 0.12,
        1.08 + pose.bounce * 0.15,
        1.08,
      );
    if (moving && t >= nextBlink) {
      blinkAt = t;
      nextBlink = t + 3.1 + Math.random() * 3.4;
    }
    const blink = moving
      ? 1 -
        0.97 *
          Math.sin(Math.min(1, Math.max(0, (t - blinkAt) / 0.19)) * Math.PI)
      : 1;
    for (const { eye, pupil, eyebrow, side } of model.eyes) {
      eye.scale.y = blink;
      pupil.position.x = pose.gazeX;
      pupil.position.y = pose.gazeY;
      eyebrow.position.y =
        1.535 + (thinking && side === 1 ? 0.055 : 0) + (happy ? 0.03 : 0);
      eyebrow.rotation.z = side * pose.brow;
    }
    const mouth =
      diggingNow && t >= talkUntil
        ? {
            lift: 1,
            aim: 0,
            strike: 14,
            impact: 14,
            lever: 14,
            scoop: 2,
            recover: 15,
            think: 8,
          }[dig.phase]
        : mouthFrame(
            thinking ? "thinking" : action,
            t,
            moving && t < talkUntil,
          );
    setMouthFrame(assets.mouths, mouth);
    canvas.dataset.mouth = String(mouth);
    model.grass.forEach((g, i) => {
      g.rotation.z = moving ? Math.sin(t * 1.65 + i * 0.7) * 0.08 : 0;
    });
    waveFlag(model.flag.geometry, model.flagRest, moving ? t : 0.5);
    if (!digging && clock > soilUntil) soilTarget = 0;
    soilAmount +=
      (soilTarget - soilAmount) * (moving ? 1 - Math.exp(-dt * 7) : 1);
    model.excavation.visible = soilAmount > 0.005;
    model.soilSurface.opacity = soilAmount * 0.92;
    model.excavation.scale.set(
      0.75 + soilAmount * 0.25,
      1,
      0.75 + soilAmount * 0.25,
    );
    model.earthRim.scale.y = Math.max(0.001, soilAmount);
    model.dust.forEach((bit, i) => {
      const age = clock - particleBirths[i];
      const particle = dirtParticle(i, age, i >= 8);
      bit.visible = moving && particle.visible;
      bit.position.set(
        model.excavation.position.x + particle.x,
        model.ground.position.y + particle.y,
        model.excavation.position.z + particle.z,
      );
      bit.scale.setScalar(Math.max(0.001, particle.size));
      bit.rotation.set(age * 5 + i, age * 3 + i, age * 4);
    });
    canvas.dataset.activity = action;
    canvas.dataset.digPhase = diggingNow ? dig.phase : "idle";
    canvas.dataset.digDepth = Math.max(0, -pose.bounce).toFixed(3);
    canvas.dataset.dirtParticles = String(
      model.dust.filter((bit) => bit.visible).length,
    );
    canvas.dataset.yaw = rotation.yaw.toFixed(3);
    canvas.dataset.pitch = rotation.pitch.toFixed(3);
    try {
      render();
    } catch {
      fail();
      return;
    }
    if (moving) schedule();
  }
  function update(next: SceneState) {
    const changedActivity = state.activity !== next.activity;
    if (state.speech !== next.speech)
      talkUntil = next.speech
        ? clock + Math.min(5, 1 + next.speech.length * 0.045)
        : 0;
    state = next;
    if (changedActivity) {
      manualUntil = 0;
      activitySince = clock;
    }
    model.accents.forEach((m) => {
      m.color.set(next.accent);
      const hsl = m.color.getHSL({ h: 0, s: 0, l: 0 });
      m.color.setHSL(hsl.h, Math.min(1, hsl.s * 1.25), hsl.l * 0.76);
    });
    if (!isVisible()) {
      cancelAnimationFrame(frame);
      frame = 0;
      last = 0;
    } else schedule();
  }
  function react() {
    if (!canAnimate()) return;
    manual = (["hello", "delight", "dig"] as const)[sequence++ % 3];
    manualUntil = clock + (manual === "dig" ? DIG_CYCLE + 0.05 : 2.7);
    nextBlink = clock + 0.35;
    schedule();
  }
  function down(event: PointerEvent) {
    if (event.button !== 0) return;
    const box = canvas.getBoundingClientRect();
    if (
      !rotation.begin(
        event.pointerId,
        event.clientX,
        event.clientY,
        Math.min(box.width, box.height),
      )
    )
      return;
    pointerAt = performance.now();
    canvas.setPointerCapture(event.pointerId);
    canvas.focus({ preventScroll: true });
    schedule();
  }
  function move(event: PointerEvent) {
    const box = canvas.getBoundingClientRect();
    pointerX = T.MathUtils.clamp(
      ((event.clientX - box.left) / box.width) * 2 - 1,
      -1,
      1,
    );
    pointerY = T.MathUtils.clamp(
      1 - ((event.clientY - box.top) / box.height) * 2,
      -1,
      1,
    );
    pointedUntil = clock + 2;
    const changed = rotation.move(
      event.pointerId,
      event.clientX,
      event.clientY,
    );
    if (changed || canAnimate()) schedule();
  }
  function up(event: PointerEvent) {
    const tapped = rotation.end(event.pointerId);
    if (canvas.hasPointerCapture(event.pointerId))
      canvas.releasePointerCapture(event.pointerId);
    if (tapped && performance.now() - pointerAt < 700) react();
    schedule();
  }
  function cancel(event: PointerEvent) {
    rotation.cancel(event.pointerId);
    if (canvas.hasPointerCapture(event.pointerId))
      canvas.releasePointerCapture(event.pointerId);
    schedule();
  }
  function keydown(event: KeyboardEvent) {
    if (["Enter", " "].includes(event.key)) {
      event.preventDefault();
      react();
    }
    if (rotation.key(event.key)) {
      event.preventDefault();
      schedule();
    }
  }
  function resize() {
    const { width, height } = canvas.getBoundingClientRect();
    if (!width || !height) return;
    renderer.setSize(width, height, false);
    // Leave headroom for the T-handle at the top of a celebratory hop.
    const halfHeight = Math.max(2.04, 2.58 / (width / height));
    camera.left = (-halfHeight * width) / height;
    camera.right = -camera.left;
    camera.top = halfHeight;
    camera.bottom = -halfHeight;
    camera.updateProjectionMatrix();
    // Resizing clears WebGL's drawing buffer. Redraw in the same layout frame
    // so the moving canvas remains visible throughout the dock transition.
    if (!disposed && !failed && isVisible()) {
      try {
        render();
      } catch {
        fail();
      }
    }
    schedule();
  }
  function fail(event?: Event) {
    event?.preventDefault();
    if (failed || disposed) return;
    failed = true;
    cancelAnimationFrame(frame);
    frame = 0;
    onFailure();
  }
  const visibility = () => update(state);
  const resizeObserver = new ResizeObserver(resize);
  resizeObserver.observe(canvas);
  reduced.addEventListener("change", visibility);
  document.addEventListener("visibilitychange", visibility);
  canvas.addEventListener("pointerdown", down);
  canvas.addEventListener("pointermove", move);
  canvas.addEventListener("pointerup", up);
  canvas.addEventListener("pointercancel", cancel);
  canvas.addEventListener("lostpointercapture", cancel);
  canvas.addEventListener("keydown", keydown);
  canvas.addEventListener("webglcontextlost", fail);
  canvas.dataset.renderer = "webgl";
  update(state);
  resize();
  return {
    update,
    dispose(releaseContext = true) {
      disposed = true;
      cancelAnimationFrame(frame);
      resizeObserver.disconnect();
      reduced.removeEventListener("change", visibility);
      document.removeEventListener("visibilitychange", visibility);
      canvas.removeEventListener("pointerdown", down);
      canvas.removeEventListener("pointermove", move);
      canvas.removeEventListener("pointerup", up);
      canvas.removeEventListener("pointercancel", cancel);
      canvas.removeEventListener("lostpointercapture", cancel);
      canvas.removeEventListener("keydown", keydown);
      canvas.removeEventListener("webglcontextlost", fail);
      disposeModel(model.root);
      disposeModel(backdrop);
      key.shadow.dispose();
      environmentMap.dispose();
      renderer.dispose();
      if (releaseContext) renderer.forceContextLoss();
      delete canvas.dataset.renderer;
    },
  };
}

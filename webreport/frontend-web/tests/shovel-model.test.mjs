import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import ts from "typescript";
import * as THREE from "three";

const source = readFileSync(
  new URL("../src/mascot/shovel-model.ts", import.meta.url),
  "utf8",
);
const { outputText } = ts.transpileModule(source, {
  compilerOptions: {
    target: ts.ScriptTarget.ES2022,
    module: ts.ModuleKind.ES2022,
  },
});
const moduleSource = outputText.replace(
  'from "three"',
  `from ${JSON.stringify(import.meta.resolve("three"))}`,
);
const {
  createShovelModel,
  waveFlag,
  disposeModel,
  setMouthFrame,
  mouthFrame,
  placeScenery,
  rotateShovel,
  fitShadowGround,
  islandTurfOutline,
  addGroundOcclusion,
} = await import(
  "data:text/javascript;base64," + Buffer.from(moduleSource).toString("base64")
);

test("the hybrid scene keeps finite geometry and bounded scene complexity", () => {
  const model = createShovelModel();
  const bounds = new THREE.Box3().setFromObject(model.root),
    size = bounds.getSize(new THREE.Vector3());
  assert.ok(size.x > 3 && size.x < 5);
  assert.ok(size.y > 3 && size.y < 5);
  assert.ok(size.z > 2 && size.z < 4);
  let triangles = 0,
    meshes = 0;
  model.root.traverse((object) => {
    if (!object.isMesh) return;
    meshes++;
    const { geometry } = object;
    for (const attribute of Object.values(geometry.attributes))
      assert.ok(Array.from(attribute.array).every(Number.isFinite));
    triangles +=
      (geometry.index?.count ?? geometry.attributes.position.count) / 3;
  });
  assert.ok(meshes < 160, `draw calls: ${meshes}`);
  assert.ok(triangles < 80000, `triangles: ${triangles}`);
  const blade = model.character.getObjectByName("blade");
  blade.geometry.computeBoundingBox();
  assert.ok(
    blade.geometry.boundingBox.getSize(new THREE.Vector3()).z > 0.2,
    "blade has a real bevelled edge and reverse side",
  );
  disposeModel(model.root);
});

test("the waving flag stays pinned to its pole, without accumulating deformation", () => {
  const model = createShovelModel(),
    attribute = model.flag.geometry.attributes.position;
  for (let t = 0; t < 20; t += 0.31) {
    waveFlag(model.flag.geometry, model.flagRest, t);
    for (let i = 0; i < attribute.count; i++) {
      assert.ok(Number.isFinite(attribute.getZ(i)));
      assert.ok(Math.abs(attribute.getZ(i)) <= 0.151);
      if (Math.abs(model.flagRest[i * 3]) < 0.00001) {
        assert.ok(Math.abs(attribute.getZ(i)) < 0.00001);
        assert.ok(
          Math.abs(attribute.getY(i) - model.flagRest[i * 3 + 1]) < 0.00001,
        );
      }
    }
  }
  waveFlag(model.flag.geometry, model.flagRest, 2);
  const first = Array.from(attribute.array);
  waveFlag(model.flag.geometry, model.flagRest, 9);
  waveFlag(model.flag.geometry, model.flagRest, 2);
  assert.deepEqual(Array.from(attribute.array), first);
  disposeModel(model.root);
});

test("switching away releases every geometry and shared material exactly once", () => {
  const assets = { mouths: new THREE.Texture(), island: new THREE.Texture() };
  const model = createShovelModel(assets),
    resources = new Map();
  addGroundOcclusion(model.root, model.ground, model.character);
  for (const texture of Object.values(assets)) resources.set(texture, 0);
  model.root.traverse((object) => {
    if (!object.isMesh) return;
    resources.set(object.geometry, 0);
    for (const m of Array.isArray(object.material)
      ? object.material
      : [object.material])
      resources.set(m, 0);
  });
  resources.forEach((_, resource) =>
    resource.addEventListener("dispose", () =>
      resources.set(resource, resources.get(resource) + 1),
    ),
  );
  disposeModel(model.root);
  for (const count of resources.values()) assert.equal(count, 1);
});

test("the invisible ground hides buried fragments without covering the painted island", () => {
  const model = createShovelModel();
  const floor = addGroundOcclusion(model.root, model.ground, model.character);
  assert.equal(floor.geometry, model.ground.geometry);
  assert.equal(floor.material.colorWrite, false);
  assert.equal(floor.material.depthWrite, true);
  assert.ok(floor.renderOrder < 0);
  model.character.traverse((object) => {
    if (!object.isMesh) return;
    for (const material of Array.isArray(object.material)
      ? object.material
      : [object.material]) {
      const plane = material.clippingPlanes[0];
      assert.ok(plane.distanceToPoint(new THREE.Vector3(0, -0.3, 0)) < 0);
      assert.ok(plane.distanceToPoint(new THREE.Vector3(0, 0.3, 0)) > 0);
      assert.equal(material.clipShadows, true);
    }
  });
  disposeModel(model.root);
});

test("all expressions sample a single inset atlas cell without bleeding", () => {
  const texture = new THREE.Texture({ width: 1254 });
  for (let i = 0; i < 16; i++) {
    setMouthFrame(texture, i);
    const col = i % 4,
      row = 3 - Math.floor(i / 4);
    assert.ok(texture.offset.x > col / 4);
    assert.ok(texture.offset.y > row / 4);
    assert.ok(texture.offset.x + texture.repeat.x < (col + 1) / 4);
    assert.ok(texture.offset.y + texture.repeat.y < (row + 1) / 4);
  }
  const talking = new Set();
  for (let time = 0; time < 5; time += 0.1) {
    for (const action of [
      "rest",
      "working",
      "thinking",
      "error",
      "hello",
      "success",
    ]) {
      const frame = mouthFrame(action, time, false);
      assert.ok(Number.isInteger(frame) && frame >= 0 && frame < 16);
    }
    talking.add(mouthFrame("welcome", time, true));
  }
  assert.ok(talking.size > 4);
  texture.dispose();
});

test("only the shovel turns, around its planted blade tip, on both axes", () => {
  const model = createShovelModel();
  const camera = new THREE.OrthographicCamera(-2.6, 2.6, 2.1, -2.1, 0.1, 40);
  camera.position.set(2.3, 4.4, 8);
  camera.lookAt(0.13, 0.94, 0);
  camera.updateMatrixWorld();
  const azimuth = Math.atan2(2.17, 8);
  placeScenery(model.island, model.flagRig, camera, azimuth);
  model.root.updateMatrixWorld(true);
  const fixed = [
    model.root,
    model.island,
    model.ground,
    model.flagRig,
    ...model.grass,
    camera,
  ];
  const matrices = fixed.map((object) => object.matrixWorld.toArray());
  const pivot = model.characterPivot.getWorldPosition(new THREE.Vector3());
  const blade = model.character.getObjectByName("blade");
  const tip = new THREE.Vector3(0, blade.geometry.boundingBox.min.y, 0.065);
  const initialHandle = new THREE.Vector3(0, 2.29, 0.04).applyMatrix4(
    blade.matrixWorld,
  );
  for (let yaw = -Math.PI; yaw <= Math.PI; yaw += 0.4)
    for (const pitch of [-1.05, -0.5, 0, 0.5, 1.05]) {
      rotateShovel(model.characterPivot, yaw, pitch, azimuth);
      model.root.updateMatrixWorld(true);
      fixed.forEach((object, i) =>
        assert.deepEqual(object.matrixWorld.toArray(), matrices[i]),
      );
      assert.ok(
        tip.clone().applyMatrix4(blade.matrixWorld).distanceTo(pivot) < 1e-6,
      );
    }
  const tiltedHandle = new THREE.Vector3(0, 2.29, 0.04).applyMatrix4(
    blade.matrixWorld,
  );
  assert.ok(tiltedHandle.distanceTo(initialHandle) > 0.5);
  const base = new THREE.Vector3(0, 1.8, 0)
    .applyMatrix4(model.flagRig.matrixWorld)
    .project(camera);
  const end = new THREE.Vector3(1.35, 1.8, 0)
    .applyMatrix4(model.flagRig.matrixWorld)
    .project(camera);
  assert.ok(end.x > base.x);
  assert.ok(Math.abs(end.y - base.y) < 1e-6);
  disposeModel(model.root);
});

test("the shadow receiver follows the painted turf boundary at every canvas aspect", () => {
  const model = createShovelModel();
  const camera = new THREE.OrthographicCamera(-2.6, 2.6, 2.1, -2.1, 0.1, 40);
  camera.position.set(2.3, 4.4, 8);
  camera.lookAt(0.13, 0.94, 0);
  camera.updateMatrixWorld();
  placeScenery(model.island, model.flagRig, camera, Math.atan2(2.17, 8));
  fitShadowGround(model.ground, model.island, camera);
  model.root.updateMatrixWorld(true);
  const vertices = model.ground.geometry.attributes.position;
  for (const aspect of [0.8, 1.2, 1.8]) {
    camera.left = -2.1 * aspect;
    camera.right = 2.1 * aspect;
    camera.updateProjectionMatrix();
    for (let i = 0; i < vertices.count; i++) {
      const world = new THREE.Vector3()
        .fromBufferAttribute(vertices, i)
        .applyMatrix4(model.ground.matrixWorld);
      assert.ok(Math.abs(world.y - 0.025) < 1e-6);
      const point = world.project(camera);
      assert.ok(
        islandTurfOutline.some(([u, v]) => {
          const painted = new THREE.Vector3(
            (u - 0.5) * 4.05,
            (0.5 - v) * 2.025,
            0,
          )
            .applyMatrix4(model.island.matrixWorld)
            .project(camera);
          return Math.hypot(painted.x - point.x, painted.y - point.y) < 1e-6;
        }),
      );
    }
  }
  disposeModel(model.root);
});

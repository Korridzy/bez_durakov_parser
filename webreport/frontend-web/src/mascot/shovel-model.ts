import * as T from "three";

export type ShovelAssets = { mouths: T.Texture; island: T.Texture };

// The painted island sits behind real geometry and a transparent shadow receiver.
export function createShovelModel(assets?: ShovelAssets) {
  const root = new T.Group();
  const material = (color: string, roughness = 0.65, metalness = 0) =>
    new T.MeshStandardMaterial({ color, roughness, metalness });
  const silver = material("#9299b6", 0.32, 0.7);
  const edge = material("#bcc7e4", 0.25, 0.75);
  const wood = material("#bd7439", 0.5);
  const coral = material("#ed786b", 0.42);
  const plum = material("#37263f", 0.47);
  const iris = material("#68409e", 0.4);
  const white = material("#fffdf8", 0.32);
  function mesh(
    g: T.BufferGeometry,
    m: T.Material | T.Material[],
    parent = root,
  ) {
    const object = new T.Mesh(g, m);
    object.castShadow = true;
    object.receiveShadow = true;
    parent.add(object);
    return object;
  }
  function ball(radius: number, m: T.Material, parent = root) {
    return mesh(new T.SphereGeometry(radius, 28, 18), m, parent);
  }
  function capsule(
    radius: number,
    length: number,
    m: T.Material,
    parent = root,
  ) {
    return mesh(new T.CapsuleGeometry(radius, length, 6, 20), m, parent);
  }
  function tube(
    points: number[][],
    radius: number,
    m: T.Material,
    parent = root,
  ) {
    const curve = new T.CatmullRomCurve3(
      points.map(([x, y, z]) => new T.Vector3(x, y, z)),
    );
    return mesh(new T.TubeGeometry(curve, 24, radius, 8, false), m, parent);
  }

  const island = mesh(
    new T.PlaneGeometry(4.05, 2.025),
    new T.MeshBasicMaterial({
      map: assets?.island ?? null,
      transparent: true,
      depthWrite: false,
      depthTest: false,
      toneMapped: false,
    }),
  );
  island.name = "painted-island";
  island.position.y = -0.38;
  island.renderOrder = -10;
  island.castShadow = island.receiveShadow = false;
  const ground = mesh(
    new T.CircleGeometry(1.53, 64),
    new T.ShadowMaterial({
      color: "#30233c",
      opacity: 0.23,
      depthWrite: false,
    }),
  );
  ground.rotation.x = -Math.PI / 2;
  ground.position.y = 0.025;
  ground.castShadow = false;
  ground.renderOrder = -1;

  const character = new T.Group();
  character.position.set(-0.22, 0.1, 0.12);
  root.add(character);
  const silhouette = new T.Shape();
  silhouette.moveTo(0, 0.06);
  silhouette.bezierCurveTo(-0.28, 0.18, -0.76, 0.53, -0.77, 1.12);
  silhouette.lineTo(-0.77, 1.39);
  silhouette.quadraticCurveTo(-0.77, 1.53, -0.63, 1.51);
  silhouette.lineTo(-0.39, 1.48);
  silhouette.quadraticCurveTo(-0.27, 1.48, -0.18, 1.66);
  silhouette.lineTo(0.18, 1.66);
  silhouette.quadraticCurveTo(0.27, 1.48, 0.39, 1.48);
  silhouette.lineTo(0.63, 1.51);
  silhouette.quadraticCurveTo(0.77, 1.53, 0.77, 1.39);
  silhouette.lineTo(0.77, 1.12);
  silhouette.bezierCurveTo(0.76, 0.53, 0.28, 0.18, 0, 0.06);
  const bladeGeometry = new T.ExtrudeGeometry(silhouette, {
    depth: 0.13,
    bevelEnabled: true,
    bevelThickness: 0.06,
    bevelSize: 0.055,
    bevelSegments: 4,
    steps: 1,
    curveSegments: 20,
  });
  mesh(bladeGeometry, [silver, edge], character).name = "blade";
  // The socket and the back ridge give the reverse side a recognisable shovel silhouette.
  capsule(0.14, 0.26, silver, character).position.set(0, 1.63, 0.04);
  const shaft = capsule(0.105, 0.38, wood, character);
  shaft.position.set(0, 1.99, 0.04);
  const handle = capsule(0.13, 0.64, wood, character);
  handle.rotation.z = Math.PI / 2;
  handle.position.set(0, 2.29, 0.04);
  for (const side of [-1, 1]) {
    const grip = capsule(0.145, 0.12, coral, character);
    grip.rotation.z = Math.PI / 2;
    grip.position.set(side * 0.39, 2.29, 0.04);
  }
  tube(
    [
      [0, 0.32, -0.01],
      [0, 0.9, -0.065],
      [0, 1.62, -0.07],
    ],
    0.047,
    silver,
    character,
  );

  const eyes = [-1, 1].map((side) => {
    const eye = new T.Group();
    eye.position.set(side * 0.285, 1.17, 0.24);
    character.add(eye);
    const rim = ball(0.258, silver, eye);
    rim.scale.set(0.93, 1.16, 0.48);
    const eyeball = ball(0.242, white, eye);
    eyeball.scale.set(0.92, 1.16, 0.55);
    eyeball.position.z = 0.023;
    const pupil = new T.Group();
    pupil.position.z = 0.155;
    pupil.scale.setScalar(1.12);
    eye.add(pupil);
    ball(0.124, iris, pupil).scale.set(0.9, 1.14, 0.46);
    const dark = ball(0.089, plum, pupil);
    dark.scale.set(0.91, 1.18, 0.4);
    dark.position.z = 0.04;
    const glint = ball(0.031, white, pupil);
    glint.position.set(-0.031, 0.057, 0.08);
    const eyebrow = new T.Group();
    character.add(eyebrow);
    const browPoints = [
      [-0.19, -0.025, 0],
      [-0.065, 0.055, 0.012],
      [0.075, 0.06, 0.006],
      [0.18, 0.005, 0],
    ];
    tube(browPoints, 0.046, plum, eyebrow);
    // Hemispherical ends close the curved tube into one smooth capsule.
    for (const point of [browPoints[0], browPoints[3]])
      ball(0.046, plum, eyebrow).position.set(point[0], point[1], point[2]);
    eyebrow.position.set(side * 0.285, 1.535, 0.34);
    return { eye, pupil, eyebrow, side };
  });
  const mouth = mesh(
    new T.PlaneGeometry(0.8, 0.64),
    new T.MeshBasicMaterial({
      map: assets?.mouths ?? null,
      transparent: true,
      depthWrite: false,
      toneMapped: false,
      polygonOffset: true,
      polygonOffsetFactor: -1,
      polygonOffsetUnits: -1,
    }),
    character,
  );
  mouth.name = "mouth-decal";
  mouth.position.set(0, 0.69, 0.195);
  mouth.castShadow = mouth.receiveShadow = false;
  if (assets) setMouthFrame(assets.mouths, 0);

  const leafMaterials = ["#477d50", "#72a34f", "#9cba63"].map((color) => {
    const m = material(color, 0.85);
    m.side = T.DoubleSide;
    return m;
  });
  const grass: T.Group[] = [];
  // Uneven little gardens leave the centre and the character's face open.
  const gardens = [
    [-1.18, 0.28, 1.05],
    [-1.02, -0.62, 0.85],
    [-0.42, -1.04, 0.8],
    [0.62, -0.92, 0.95],
    [1.18, -0.24, 1.15],
    [1.08, 0.56, 0.8],
    [-0.75, 0.97, 0.72],
  ];
  gardens.forEach(([x, z, size], i) => {
    const clump = new T.Group();
    clump.position.set(x, 0.025, z);
    clump.rotation.y = i * 2.4;
    clump.scale.setScalar(size);
    root.add(clump);
    for (let j = 0; j < 7; j++) {
      const vertices: number[] = [],
        indices: number[] = [];
      const height = 0.3 + ((j * 3) % 7) * 0.032;
      const bend = (j - 3) * 0.042;
      // A curved, ridged leaf has volume and catches light along its spine.
      for (let row = 0; row <= 6; row++) {
        const t = row / 6,
          width = Math.sin(Math.PI * (0.08 + t * 0.92)) * 0.055;
        const cx = bend * t * t,
          cy = height * t,
          cz = t * t * 0.15;
        vertices.push(
          cx - width,
          cy,
          cz,
          cx,
          cy,
          cz + width * 0.6,
          cx + width,
          cy,
          cz,
        );
        if (row < 6)
          for (let col = 0; col < 2; col++) {
            const a = row * 3 + col;
            indices.push(a, a + 3, a + 1, a + 1, a + 3, a + 4);
          }
      }
      const geometry = new T.BufferGeometry();
      geometry.setAttribute(
        "position",
        new T.Float32BufferAttribute(vertices, 3),
      );
      geometry.setIndex(indices);
      geometry.computeVertexNormals();
      const leaf = mesh(geometry, leafMaterials[j % 3], clump);
      leaf.rotation.y = j * 2.4;
      leaf.position.x = (j - 3) * 0.017;
    }
    grass.push(clump);
  });
  const flagRig = new T.Group();
  root.add(flagRig);
  const pole = capsule(0.022, 1.94, material("#695071", 0.42, 0.25), flagRig);
  pole.position.y = 1.015;
  ball(0.042, wood, flagRig).position.y = 2.03;
  const flagMaterial = coral.clone();
  flagMaterial.side = T.DoubleSide;
  const flagGeometry = new T.PlaneGeometry(1.35, 0.34, 32, 8);
  flagGeometry.translate(0.675, 0, 0);
  const flag = mesh(flagGeometry, flagMaterial, flagRig);
  flag.position.set(0.025, 1.8, 0);
  flag.castShadow = false;
  const flagRest = Float32Array.from(flag.geometry.attributes.position.array);

  const earthMaterials = ["#4f3324", "#6f442b", "#915733"].map((color) =>
    material(color, 1),
  );
  const clodGeometry = new T.DodecahedronGeometry(1, 0);
  const dust = Array.from({ length: 20 }, (_, i) => {
    const bit = mesh(clodGeometry, earthMaterials[i % 3]);
    bit.visible = false;
    return bit;
  });
  const excavation = new T.Group();
  excavation.position.set(-0.22, ground.position.y + 0.003, 0.12);
  excavation.visible = false;
  root.add(excavation);
  const soil = mesh(
    new T.CircleGeometry(0.4, 40),
    material("#5c3b2e", 1),
    excavation,
  );
  soil.name = "dug-soil";
  soil.rotation.x = -Math.PI / 2;
  soil.scale.y = 0.78;
  soil.castShadow = false;
  const soilSurface = soil.material as T.MeshStandardMaterial;
  soilSurface.transparent = true;
  soilSurface.depthWrite = false;
  soilSurface.polygonOffset = true;
  soilSurface.polygonOffsetFactor = -1;
  const earthRim = new T.Group();
  excavation.add(earthRim);
  for (let i = 0; i < 16; i++) {
    const angle = i * 2.39996;
    const clod = mesh(clodGeometry, earthMaterials[i % 3], earthRim);
    const size = 0.045 + (i % 4) * 0.017;
    clod.position.set(
      Math.cos(angle) * (0.28 + (i % 4) * 0.025),
      size * (0.22 + (i % 3) * 0.14),
      Math.sin(angle) * (0.23 + (i % 3) * 0.027),
    );
    clod.scale.set(size * 1.7, size * 0.72, size);
    clod.rotation.set(i * 0.7, angle, i * 1.3);
  }
  for (let i = 0; i < 7; i++) {
    const clod = mesh(clodGeometry, earthMaterials[(i + 1) % 3], earthRim);
    const size = 0.075 + (i % 3) * 0.025;
    clod.position.set(
      0.48 + Math.cos(i * 2.4) * 0.13,
      size * 0.4 + (i === 6 ? 0.08 : 0),
      -0.08 + Math.sin(i * 2.4) * 0.13,
    );
    clod.scale.set(size * 1.2, size * 0.85, size);
    clod.rotation.set(i, i * 0.7, i * 0.2);
  }
  // Put the manipulation origin at the actual bevelled blade tip. Animation
  // lives in the inner group, while the outer pivot stays planted on the turf.
  bladeGeometry.computeBoundingBox();
  const body = new T.Group();
  body.position.set(0, -bladeGeometry.boundingBox!.min.y, -0.065);
  while (character.children.length) body.add(character.children[0]);
  character.add(body);
  character.position.set(0, 0, 0);
  const characterPivot = new T.Group();
  characterPivot.name = "shovel-base-pivot";
  characterPivot.position.set(-0.22, ground.position.y, 0.12);
  characterPivot.add(character);
  root.add(characterPivot);
  return {
    root,
    character,
    characterPivot,
    ground,
    eyes,
    mouth,
    island,
    flagRig,
    grass,
    flag,
    flagRest,
    dust,
    excavation,
    earthRim,
    soilSurface,
    accents: [coral, flagMaterial],
  };
}

export function addGroundOcclusion(
  root: T.Group,
  ground: T.Mesh,
  character: T.Group,
) {
  // The colour comes from the painting; this surface writes only depth.
  const floor = new T.Mesh(
    ground.geometry,
    new T.MeshBasicMaterial({ colorWrite: false, depthWrite: true }),
  );
  floor.name = "island-depth-mask";
  floor.position.copy(ground.position);
  floor.rotation.copy(ground.rotation);
  floor.renderOrder = -5;
  root.add(floor);
  // Also clip buried fragments that would otherwise peek out below the painted
  // rock silhouette. The plane is in world space, so manual rotation still works.
  const surface = new T.Plane(new T.Vector3(0, 1, 0), -ground.position.y);
  character.traverse((object) => {
    if (!(object instanceof T.Mesh)) return;
    const materials = Array.isArray(object.material)
      ? object.material
      : [object.material];
    materials.forEach((material) => {
      material.clippingPlanes = [surface];
      material.clipShadows = true;
    });
  });
  return floor;
}

export function waveFlag(
  geometry: T.BufferGeometry,
  rest: Float32Array,
  time: number,
) {
  const vertices = geometry.attributes.position;
  for (let i = 0; i < vertices.count; i++) {
    const x = rest[i * 3],
      y = rest[i * 3 + 1];
    const free = x / 1.35;
    vertices.setXYZ(
      i,
      x,
      y + Math.sin(time * 2 - free * 4) * 0.055 * free,
      Math.sin(free * 7 - time * 2.4) * 0.15 * free,
    );
  }
  vertices.needsUpdate = true;
  geometry.computeVertexNormals();
}

export function disposeModel(root: T.Object3D) {
  const geometries = new Set<T.BufferGeometry>(),
    materials = new Set<T.Material>(),
    textures = new Set<T.Texture>();
  root.traverse((object) => {
    if (!(object instanceof T.Mesh)) return;
    geometries.add(object.geometry);
    (Array.isArray(object.material)
      ? object.material
      : [object.material]
    ).forEach((m) => materials.add(m));
  });
  geometries.forEach((g) => g.dispose());
  materials.forEach((m) => {
    const map = (m as T.MeshBasicMaterial).map;
    if (map) textures.add(map);
    m.dispose();
  });
  textures.forEach((texture) => texture.dispose());
}

// Half a texel of inset prevents neighbouring cells bleeding into the decal.
export function setMouthFrame(texture: T.Texture, frame: number) {
  const index = T.MathUtils.clamp(Math.floor(frame), 0, 15);
  const inset =
    0.5 / ((texture.image as { width?: number } | undefined)?.width || 1254);
  texture.repeat.set(0.25 - inset * 2, 0.25 - inset * 2);
  texture.offset.set(
    (index % 4) / 4 + inset,
    (3 - Math.floor(index / 4)) / 4 + inset,
  );
}

export function mouthFrame(action: string, time: number, talking: boolean) {
  if (talking) return [4, 5, 0, 6, 5, 7, 1, 0][Math.floor(time * 8) % 8];
  if (action === "error") return 11;
  if (action === "thinking") return Math.floor(time / 2) % 2 ? 8 : 9;
  if (action === "dig" || action === "working")
    return Math.floor(time * 2) % 3 ? 14 : 4;
  if (action === "hello" || action === "delight" || action === "success")
    return Math.floor(time * 2) % 3 ? 2 : 12;
  return 0;
}

// Set once for the fixed camera. Only the character pivot changes afterwards.
export function placeScenery(
  island: T.Object3D,
  flagRig: T.Object3D,
  camera: T.Camera,
  azimuth: number,
) {
  island.quaternion.copy(camera.quaternion);
  flagRig.rotation.y = azimuth;
  flagRig.position.set(
    Math.cos(azimuth) * 0.88 - Math.sin(azimuth) * 0.65,
    0.025,
    -Math.sin(azimuth) * 0.88 - Math.cos(azimuth) * 0.65,
  );
}

export function rotateShovel(
  pivot: T.Object3D,
  yaw: number,
  pitch: number,
  cameraAzimuth: number,
) {
  const side = new T.Vector3(
    Math.cos(cameraAzimuth),
    0,
    -Math.sin(cameraAzimuth),
  );
  pivot.quaternion.setFromAxisAngle(new T.Vector3(0, 1, 0), yaw);
  pivot.quaternion.premultiply(
    new T.Quaternion().setFromAxisAngle(side, pitch),
  );
}

// The inset turf outline in island.png, normalised from its top-left corner.
// Project it onto the horizontal receiver so shadows stop before the rock edge.
export const islandTurfOutline = [
  [0.15, 0.23],
  [0.2, 0.185],
  [0.29, 0.151],
  [0.41, 0.125],
  [0.54, 0.129],
  [0.66, 0.149],
  [0.76, 0.185],
  [0.84, 0.226],
  [0.869, 0.281],
  [0.831, 0.329],
  [0.755, 0.379],
  [0.64, 0.433],
  [0.52, 0.461],
  [0.41, 0.447],
  [0.32, 0.407],
  [0.25, 0.358],
  [0.174, 0.324],
  [0.136, 0.279],
] as const;

export function fitShadowGround(
  ground: T.Mesh,
  island: T.Mesh,
  camera: T.Camera,
) {
  const direction = camera.getWorldDirection(new T.Vector3());
  const size = new T.Vector3();
  island.geometry.computeBoundingBox();
  island.geometry.boundingBox!.getSize(size);
  island.updateWorldMatrix(true, false);
  const outline = islandTurfOutline.map(([u, v]) => {
    const point = island.localToWorld(
      new T.Vector3((u - 0.5) * size.x, (0.5 - v) * size.y, 0),
    );
    point.addScaledVector(
      direction,
      (ground.position.y - point.y) / direction.y,
    );
    return new T.Vector2(point.x, -point.z);
  });
  ground.geometry.dispose();
  ground.geometry = new T.ShapeGeometry(new T.Shape(outline));
}

/** Decorative edge sprites leave the reading column clear and ignore pointer input. */
export function Atmosphere() {
  return (
    <div className="atmosphere" aria-hidden="true">
      <img
        className="scenery-architecture architecture-left"
        src="/scenery/architecture-left.png"
        alt=""
        draggable={false}
      />
      <img
        className="scenery-architecture architecture-right"
        src="/scenery/architecture-right.png"
        alt=""
        draggable={false}
      />
      {(["left", "right"] as const).map((side) => (
        <div className={`meadow-edge meadow-${side}`} key={side}>
          <img
            className="meadow-corner grass-clump"
            src="/scenery/grass-corner.png"
            alt=""
            draggable={false}
          />
          <img
            className="meadow-tuft meadow-tuft-near grass-clump"
            src="/scenery/grass-tuft.png"
            alt=""
            draggable={false}
          />
          <img
            className="meadow-tuft meadow-tuft-far grass-clump"
            src="/scenery/grass-tuft.png"
            alt=""
            draggable={false}
          />
        </div>
      ))}
    </div>
  );
}

import defaultLayout from "./brand-layout.json";

export type BrandLayout = typeof defaultLayout;
export { defaultLayout as brandLayout };

// Independent image elements share one coordinate system. Position and size
// come from the same layout file used to build the browser icon.
export function BrandMark({
  layout = defaultLayout,
}: {
  layout?: BrandLayout;
}) {
  return (
    <svg
      className="brand-mark"
      viewBox={`0 0 ${layout.canvas} ${layout.canvas}`}
      aria-hidden="true"
    >
      {layout.layers.map((layer) => (
        <image
          key={layer.id}
          data-brand-layer={layer.id}
          href={`/brand/${layer.asset}`}
          x={layer.x}
          y={layer.y}
          width={layer.size}
          height={layer.size}
        />
      ))}
    </svg>
  );
}

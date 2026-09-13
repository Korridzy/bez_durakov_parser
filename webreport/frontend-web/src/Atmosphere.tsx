/** Quiet original scenery, below all interactive UI and absent from accessibility. */
export function Atmosphere() {
  return (
    <div className="atmosphere" aria-hidden="true">
      <svg
        className="distant-city city-left"
        viewBox="0 0 230 410"
        fill="none"
        focusable="false"
      >
        <path
          d="M0 410V190l24-10 22 10v90l22-8v-96l22-11 18 12v-76l27-17 30 18v207l23-7V228l20-11 22 11v182Z"
          fill="#c5b8e1"
        />
        <path
          d="m24 180 22 10v160l-22 10Zm66-15 18 12v157l-18 12Zm45-81 30 18v247l-30 11Zm73 133 22 11v182h-22Z"
          fill="#b1a2d1"
        />
        <path
          d="M126 244v-68q17-28 30 0v68Zm-54 63v-58q13-22 24 0v58Z"
          fill="#faf7fc"
        />
      </svg>
      <svg
        className="distant-city city-right"
        viewBox="0 0 230 410"
        fill="none"
        focusable="false"
      >
        <path
          d="M0 410V274l30-14v-78l24-10 19 10v112l29-9V94l25-16 28 16v148l26-13V31l24-14 25 14v379Z"
          fill="#c8b9e3"
        />
        <path
          d="m127 78 28 16v269l-28 12Zm78-61 25 14v379h-25ZM54 172l19 10v112l-19 13Z"
          fill="#b4a2d6"
        />
        <path
          d="M108 276v-67q18-28 34 0v67Zm81-80v-50q13-25 26 0v50Z"
          fill="#fbf8fc"
        />
      </svg>
      {["left", "right"].map((side) => (
        <svg
          key={side}
          className={`foreground-grass grass-${side}`}
          viewBox="0 0 260 200"
          fill="none"
          focusable="false"
        >
          {[0, 1, 2].map((layer) => (
            <g key={layer} opacity={0.42 + layer * 0.23}>
              {Array.from({ length: 9 }, (_, i) => {
                const x = 8 + i * 27 + layer * 7,
                  height = 30 + ((i * 37 + layer * 23) % 95),
                  lean = -24 + ((i * 19 + layer * 7) % 48);
                return (
                  <g className="grass-clump" key={i}>
                    <path
                      d={`M${x},205 Q${x + lean * 0.15},${200 - height * 0.7} ${x + lean},${200 - height} Q${x + lean * 0.6 + 3},${200 - height * 0.45} ${x + 5},205Z`}
                      fill={["#b0bfa8", "#859e87", "#5f8273"][layer]}
                    />
                    <path
                      d={`M${x + 3},204 Q${x - 9},${190 - height * 0.4} ${x - 17},${183 - height * 0.6} Q${x - 1},${185 - height * 0.35} ${x + 6},204Z`}
                      fill={layer === 2 ? "#8ea486" : "#b3c3a2"}
                    />
                  </g>
                );
              })}
            </g>
          ))}
          {[34, 107, 182].map((x, i) => {
            const y = 43 + i * 21;
            return (
              <g className="grass-clump" key={x}>
                <path
                  d={`M${x + 10},202 Q${x + 22},${y + 54} ${x},${y}`}
                  stroke="#839977"
                  strokeWidth="1.4"
                />
                {[-1, 0, 1].map((n) => (
                  <ellipse
                    key={n}
                    cx={x + n * 3}
                    cy={y + Math.abs(n) * 5}
                    rx="2.7"
                    ry="6"
                    transform={`rotate(${n * 26} ${x + n * 3} ${y + Math.abs(n) * 5})`}
                    fill={i === 1 ? "#b59cbb" : "#c6bda0"}
                  />
                ))}
              </g>
            );
          })}
        </svg>
      ))}
    </div>
  );
}

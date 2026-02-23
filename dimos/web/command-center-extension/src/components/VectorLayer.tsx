import * as React from "react";

import { Vector } from "../types";

interface VectorLayerProps {
  vector: Vector;
  label: string;
  worldToPx: (x: number, y: number) => [number, number];
}

const VectorLayer = React.memo<VectorLayerProps>(({ vector, label, worldToPx }) => {
  const [cx, cy] = worldToPx(vector.coords[0]!, vector.coords[1]!);
  const yaw: number | undefined = vector.coords[3]; // optional yaw in world radians
  const text = `${label} (${vector.coords[0]!.toFixed(2)}, ${vector.coords[1]!.toFixed(2)})`;

  // Build directional arrow if yaw is available.
  // World: yaw=0 → east (+x), yaw=π/2 → north (+y, screen up → -y).
  let arrowEl: React.ReactNode = null;
  if (yaw !== undefined) {
    const arrowLen = 28;
    const headLen = 10;
    const shaftWidth = 3;
    const headHalfWidth = 8;

    // Convert world yaw to screen direction (flip y because screen y points down)
    const dx = Math.cos(yaw);
    const dy = -Math.sin(yaw);

    const shaftEndX = cx + dx * (arrowLen - headLen);
    const shaftEndY = cy + dy * (arrowLen - headLen);
    const tipX = cx + dx * arrowLen;
    const tipY = cy + dy * arrowLen;

    // Perpendicular unit vector for arrowhead width
    const px = -dy;
    const py = dx;

    const headPoints = [
      `${shaftEndX + px * headHalfWidth},${shaftEndY + py * headHalfWidth}`,
      `${tipX},${tipY}`,
      `${shaftEndX - px * headHalfWidth},${shaftEndY - py * headHalfWidth}`,
    ].join(" ");

    arrowEl = (
      <>
        <line x1={cx} y1={cy} x2={shaftEndX} y2={shaftEndY} stroke="red" strokeWidth={shaftWidth} />
        <polygon points={headPoints} fill="red" />
      </>
    );
  }

  return (
    <>
      <g className="vector-marker">
        <circle cx={cx} cy={cy} r={6} fill="red" opacity={0.9} />
        {arrowEl}
      </g>
      <g>
        <rect
          x={cx + 24}
          y={cy + 14}
          width={text.length * 7}
          height={18}
          fill="black"
          stroke="black"
          opacity={0.75}
        />
        <text x={cx + 25} y={cy + 25} fontSize="1em" fill="white">
          {text}
        </text>
      </g>
    </>
  );
});

VectorLayer.displayName = "VectorLayer";

export default VectorLayer;

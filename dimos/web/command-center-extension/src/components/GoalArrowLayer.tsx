import * as React from "react";

interface GoalArrowLayerProps {
  startPx: [number, number];
  endPx: [number, number];
}

const ARROW_HEAD_LENGTH = 12;
const ARROW_HEAD_WIDTH = 6;

const GoalArrowLayer: React.FC<GoalArrowLayerProps> = ({ startPx, endPx }) => {
  const [x1, y1] = startPx;
  const [x2, y2] = endPx;
  const dx = x2 - x1;
  const dy = y2 - y1;
  const len = Math.sqrt(dx * dx + dy * dy);
  if (len < 1) return null;

  const angle = Math.atan2(dy, dx) * (180 / Math.PI);

  // Shorten line so arrowhead sits at the tip
  const ux = dx / len;
  const uy = dy / len;
  const lineEndX = x2 - ux * ARROW_HEAD_LENGTH;
  const lineEndY = y2 - uy * ARROW_HEAD_LENGTH;

  return (
    <g pointerEvents="none">
      {/* Origin circle */}
      <circle cx={x1} cy={y1} r={6} fill="none" stroke="#00ff88" strokeWidth={2} opacity={0.9} />
      <circle cx={x1} cy={y1} r={3} fill="#00ff88" opacity={0.9} />
      {/* Shaft */}
      <line
        x1={x1} y1={y1} x2={lineEndX} y2={lineEndY}
        stroke="#00ff88" strokeWidth={2} opacity={0.9}
      />
      {/* Arrowhead */}
      <polygon
        points={`0,0 ${-ARROW_HEAD_LENGTH},${-ARROW_HEAD_WIDTH} ${-ARROW_HEAD_LENGTH},${ARROW_HEAD_WIDTH}`}
        fill="#00ff88"
        opacity={0.9}
        transform={`translate(${x2},${y2}) rotate(${angle})`}
      />
    </g>
  );
};

export default GoalArrowLayer;

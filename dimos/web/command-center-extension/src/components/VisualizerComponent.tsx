import * as d3 from "d3";
import * as React from "react";

import { Costmap, Path, Vector } from "../types";
import CostmapLayer from "./CostmapLayer";
import GoalArrowLayer from "./GoalArrowLayer";
import PathLayer from "./PathLayer";
import VectorLayer from "./VectorLayer";

interface VisualizerComponentProps {
  costmap: Costmap | null;
  robotPose: Vector | null;
  path: Path | null;
  goalArrow?: { startPx: [number, number]; endPx: [number, number] } | null;
  committedGoal?: { worldX: number; worldY: number; yaw?: number } | null;
}

const VisualizerComponent: React.FC<VisualizerComponentProps> = ({ costmap, robotPose, path, goalArrow, committedGoal }) => {
  const svgRef = React.useRef<SVGSVGElement>(null);
  const [dimensions, setDimensions] = React.useState({ width: 800, height: 600 });
  const { width, height } = dimensions;

  React.useEffect(() => {
    if (!svgRef.current?.parentElement) {
      return;
    }

    const updateDimensions = () => {
      const rect = svgRef.current?.parentElement?.getBoundingClientRect();
      if (rect) {
        setDimensions({ width: rect.width, height: rect.height });
      }
    };

    updateDimensions();
    const observer = new ResizeObserver(updateDimensions);
    observer.observe(svgRef.current.parentElement);

    return () => {
      observer.disconnect();
    };
  }, []);

  const { worldToPx } = React.useMemo(() => {
    if (!costmap) {
      return { worldToPx: undefined };
    }

    const {
      grid: { shape },
      origin,
      resolution,
    } = costmap;
    const rows = shape[0]!;
    const cols = shape[1]!;

    const axisMargin = { left: 60, bottom: 40 };
    const availableWidth = width - axisMargin.left;
    const availableHeight = height - axisMargin.bottom;

    const cell = Math.min(availableWidth / cols, availableHeight / rows);
    const gridW = cols * cell;
    const gridH = rows * cell;
    const offsetX = axisMargin.left + (availableWidth - gridW) / 2;
    const offsetY = (availableHeight - gridH) / 2;

    const xScale = d3
      .scaleLinear()
      .domain([origin.coords[0]!, origin.coords[0]! + cols * resolution])
      .range([offsetX, offsetX + gridW]);

    const yScale = d3
      .scaleLinear()
      .domain([origin.coords[1]!, origin.coords[1]! + rows * resolution])
      .range([offsetY + gridH, offsetY]);

    const worldToPxFn = (x: number, y: number): [number, number] => [xScale(x), yScale(y)];

    return { worldToPx: worldToPxFn };
  }, [costmap, width, height]);

  return (
    <div className="visualizer-container" style={{ width: "100%", height: "100%" }}>
      <svg
        ref={svgRef}
        width="100%"
        height="100%"
        viewBox={`0 0 ${width} ${height}`}
        preserveAspectRatio="xMidYMid meet"
        style={{
          backgroundColor: "black",
          pointerEvents: "none",
        }}
      >
        {costmap && <CostmapLayer costmap={costmap} width={width} height={height} />}
        {path && worldToPx && <PathLayer path={path} worldToPx={worldToPx} />}
        {robotPose && worldToPx && (
          <VectorLayer vector={robotPose} label="robot" worldToPx={worldToPx} />
        )}
        {committedGoal && worldToPx && (() => {
          const [gx, gy] = worldToPx(committedGoal.worldX, committedGoal.worldY);
          const yaw = committedGoal.yaw;
          const arrowLen = 28, headLen = 10, headHalfWidth = 8;
          const dx = yaw !== undefined ? Math.cos(yaw) : 0;
          const dy = yaw !== undefined ? -Math.sin(yaw) : 0;
          const shaftEndX = gx + dx * (arrowLen - headLen);
          const shaftEndY = gy + dy * (arrowLen - headLen);
          const tipX = gx + dx * arrowLen;
          const tipY = gy + dy * arrowLen;
          const px = -dy, py = dx;
          const headPts = [
            `${shaftEndX + px * headHalfWidth},${shaftEndY + py * headHalfWidth}`,
            `${tipX},${tipY}`,
            `${shaftEndX - px * headHalfWidth},${shaftEndY - py * headHalfWidth}`,
          ].join(" ");
          return (
            <g>
              <circle cx={gx} cy={gy} r={6} fill="none" stroke="#00cc44" strokeWidth={2} />
              <circle cx={gx} cy={gy} r={3} fill="#00cc44" />
              {yaw !== undefined && (
                <>
                  <line x1={gx} y1={gy} x2={shaftEndX} y2={shaftEndY} stroke="#00cc44" strokeWidth={3} />
                  <polygon points={headPts} fill="#00cc44" />
                </>
              )}
            </g>
          );
        })()}
        {goalArrow && (
          <GoalArrowLayer startPx={goalArrow.startPx} endPx={goalArrow.endPx} />
        )}
      </svg>
    </div>
  );
};

export default React.memo(VisualizerComponent);

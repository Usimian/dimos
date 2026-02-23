import * as d3 from "d3";
import * as React from "react";

import { AppState } from "../types";
import VisualizerComponent from "./VisualizerComponent";

interface VisualizerWrapperProps {
  data: AppState;
  onWorldClick: (worldX: number, worldY: number, yaw?: number) => void;
}

const DRAG_THRESHOLD_PX = 8;

const VisualizerWrapper: React.FC<VisualizerWrapperProps> = ({ data, onWorldClick }) => {
  const containerRef = React.useRef<HTMLDivElement>(null);

  // Drag state
  const dragRef = React.useRef<{
    startPx: [number, number];
    worldX: number;
    worldY: number;
  } | null>(null);
  const [goalArrow, setGoalArrow] = React.useState<{
    startPx: [number, number];
    endPx: [number, number];
  } | null>(null);

  const getScales = React.useCallback(() => {
    if (!data.costmap || !containerRef.current) return null;

    const svgElement = containerRef.current.querySelector("svg");
    if (!svgElement) return null;
    const svgRect = svgElement.getBoundingClientRect();

    const {
      grid: { shape },
      origin,
      resolution,
    } = data.costmap;
    const rows = shape[0]!;
    const cols = shape[1]!;

    const axisMargin = { left: 60, bottom: 40 };
    const availableWidth = svgRect.width - axisMargin.left;
    const availableHeight = svgRect.height - axisMargin.bottom;

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

    return { xScale, yScale, svgRect };
  }, [data.costmap]);

  const svgCoords = React.useCallback(
    (clientX: number, clientY: number) => {
      const scales = getScales();
      if (!scales) return null;
      const { svgRect } = scales;
      return [clientX - svgRect.left, clientY - svgRect.top] as [number, number];
    },
    [getScales],
  );

  const worldCoords = React.useCallback(
    (clientX: number, clientY: number) => {
      const scales = getScales();
      if (!scales) return null;
      const { xScale, yScale, svgRect } = scales;
      const px = clientX - svgRect.left;
      const py = clientY - svgRect.top;
      return { worldX: xScale.invert(px), worldY: yScale.invert(py) };
    },
    [getScales],
  );

  const handleMouseDown = React.useCallback(
    (event: React.MouseEvent) => {
      if (!data.costmap) return;
      event.preventDefault();
      const coords = worldCoords(event.clientX, event.clientY);
      const pxCoords = svgCoords(event.clientX, event.clientY);
      if (!coords || !pxCoords) return;
      dragRef.current = {
        startPx: pxCoords,
        worldX: coords.worldX,
        worldY: coords.worldY,
      };
      setGoalArrow(null);
    },
    [data.costmap, worldCoords, svgCoords],
  );

  const handleMouseMove = React.useCallback(
    (event: React.MouseEvent) => {
      if (!dragRef.current) return;
      const endPx = svgCoords(event.clientX, event.clientY);
      if (!endPx) return;
      const [sx, sy] = dragRef.current.startPx;
      const [ex, ey] = endPx;
      const dist = Math.sqrt((ex - sx) ** 2 + (ey - sy) ** 2);
      if (dist > DRAG_THRESHOLD_PX) {
        setGoalArrow({ startPx: dragRef.current.startPx, endPx });
      }
    },
    [svgCoords],
  );

  const handleMouseUp = React.useCallback(
    (event: React.MouseEvent) => {
      if (!dragRef.current) return;
      const { startPx, worldX, worldY } = dragRef.current;
      dragRef.current = null;
      setGoalArrow(null);

      const endPx = svgCoords(event.clientX, event.clientY);
      if (!endPx) {
        onWorldClick(worldX, worldY);
        return;
      }

      const [sx, sy] = startPx;
      const [ex, ey] = endPx;
      const screenDx = ex - sx;
      const screenDy = ey - sy;
      const dist = Math.sqrt(screenDx ** 2 + screenDy ** 2);

      if (dist > DRAG_THRESHOLD_PX) {
        // Y axis is flipped between screen and world: world yaw = atan2(-screenDy, screenDx)
        const yaw = Math.atan2(-screenDy, screenDx);
        onWorldClick(worldX, worldY, yaw);
      } else {
        onWorldClick(worldX, worldY);
      }
    },
    [svgCoords, onWorldClick],
  );

  const handleMouseLeave = React.useCallback(() => {
    if (dragRef.current) {
      // Commit with no heading if mouse leaves
      const { worldX, worldY } = dragRef.current;
      dragRef.current = null;
      setGoalArrow(null);
      onWorldClick(worldX, worldY);
    }
  }, [onWorldClick]);

  return (
    <div
      ref={containerRef}
      style={{ width: "100%", height: "100%", cursor: "crosshair" }}
      onMouseDown={handleMouseDown}
      onMouseMove={handleMouseMove}
      onMouseUp={handleMouseUp}
      onMouseLeave={handleMouseLeave}
    >
      <VisualizerComponent
        costmap={data.costmap}
        robotPose={data.robotPose}
        path={data.path}
        goalArrow={goalArrow}
      />
    </div>
  );
};

export default VisualizerWrapper;

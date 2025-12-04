# Modular Robot Architecture: Removing Model Dependencies

## Overview

This document describes the new modular architecture for DIMOS robots that removes hard-coded model dependencies (YOLO, Metric3D, FastSAM, CLIP, etc.) from robot classes. The solution enables robots to run on CPU-only environments while providing optional AI capabilities when dependencies are available.

## Problem Statement

The original Unitree Go2 implementation had several issues:

1. **Hard-coded model dependencies**: Direct imports of YOLO, Metric3D, etc. in robot classes
2. **No CPU-only operation**: Could not run without heavy AI models
3. **Monolithic design**: All AI capabilities were bundled together
4. **Poor modularity**: Adding new AI features required modifying robot classes
5. **Resource inefficiency**: All models loaded even when not needed

## Solution Architecture

### 1. Stream Processor Framework

**Core Components:**
- `StreamProcessor` (Abstract Base Class): Defines interface for all processors
- `StreamProcessorRegistry`: Manages available processors
- `StreamProcessorPipeline`: Chains multiple processors together
- `PassthroughProcessor`: No-op processor for testing

**Key Files:**
- `dimos/stream/stream_processor.py`: Core framework
- `dimos/stream/processors/__init__.py`: Dynamic processor loading
- `dimos/stream/processors/*.py`: Individual processor implementations

### 2. Dynamic Processor Loading

```python
# Processors are loaded only if dependencies are available
def try_import_processor(module_name: str, class_name: str, processor_name: str) -> bool:
    try:
        module = __import__(f"dimos.stream.processors.{module_name}", fromlist=[class_name])
        processor_class = getattr(module, class_name)
        register_processor(processor_name, processor_class)
        return True
    except ImportError:
        return False  # Gracefully handle missing dependencies
```

### 3. Modular Robot Implementation

**New Unitree Go2 Features:**
- Optional `stream_processors` parameter
- Configurable `processor_configs` 
- Graceful degradation when processors unavailable
- CPU-first design with optional GPU acceleration

```python
# CPU-only robot (no AI models)
robot = UnitreeGo2(
    use_ros=True,
    disable_video_stream=True  # Basic movement only
)

# Robot with optional AI capabilities
robot = UnitreeGo2(
    use_ros=True,
    stream_processors=["person_tracking", "object_detection"],
    processor_configs={
        "person_tracking": {"device": "cpu", "model_path": "yolo11n.pt"},
        "object_detection": {"device": "cpu", "confidence_threshold": 0.5}
    }
)
```

## Available Stream Processors

### 1. Person Tracking Processor
- **Dependencies**: YOLO (ultralytics)
- **Features**: Person detection, distance estimation, tracking
- **Configuration**:
  ```python
  {
      "model_path": "yolo11n.pt",
      "device": "cpu|cuda",
      "camera_intrinsics": [fx, fy, cx, cy],
      "camera_pitch": 0.0,
      "camera_height": 1.0
  }
  ```

### 2. Object Tracking Processor  
- **Dependencies**: OpenCV, Metric3D
- **Features**: CSRT tracking, depth estimation, re-identification
- **Configuration**:
  ```python
  {
      "device": "cpu|cuda",
      "reid_threshold": 5,
      "reid_fail_tolerance": 10,
      "gt_depth_scale": 1000.0
  }
  ```

### 3. Object Detection Processor
- **Dependencies**: YOLO (ultralytics)
- **Features**: Multi-class object detection, filtering
- **Configuration**:
  ```python
  {
      "model_path": "yolo11n.pt",
      "device": "cpu|cuda", 
      "class_filter": [0, 1, 2],  # person, bicycle, car
      "confidence_threshold": 0.5
  }
  ```

### 4. Depth Estimation Processor
- **Dependencies**: Metric3D
- **Features**: Monocular depth estimation, visualization
- **Configuration**:
  ```python
  {
      "device": "cpu|cuda",
      "gt_depth_scale": 1000.0,
      "camera_intrinsics": [fx, fy, cx, cy]
  }
  ```

### 5. Semantic Segmentation Processor
- **Dependencies**: FastSAM (ultralytics)
- **Features**: Instance segmentation, mask generation
- **Configuration**:
  ```python
  {
      "model_path": "FastSAM-s.pt",
      "device": "cpu|cuda",
      "confidence_threshold": 0.4,
      "iou_threshold": 0.9
  }
  ```

## Usage Examples

### Basic CPU-Only Robot

```python
from dimos.robot.unitree.unitree_go2 import UnitreeGo2

# Minimal robot for basic movement
robot = UnitreeGo2(
    use_ros=True,
    use_webrtc=False,
    disable_video_stream=True  # No video processing
)

# Basic movement commands work without any AI models
robot.move_vel(x=0.1, y=0.0, yaw=0.0, duration=2.0)
robot.cleanup()
```

### Robot with AI Capabilities

```python
from dimos.robot.unitree.unitree_go2 import UnitreeGo2
from dimos.stream.processors import get_loaded_processors

# Check what's available
available = get_loaded_processors()
print(f"Available processors: {available}")

# Configure AI-enabled robot
robot = UnitreeGo2(
    use_ros=True,
    stream_processors=["person_tracking", "object_detection"],
    processor_configs={
        "person_tracking": {
            "device": "cpu",  # CPU-compatible
            "model_path": "yolo11n.pt"  # Lightweight model
        },
        "object_detection": {
            "device": "cpu",
            "confidence_threshold": 0.6,
            "class_filter": [0]  # Person only
        }
    }
)

# Access processed video stream
processed_stream = robot.get_processed_stream("main")
if processed_stream:
    def on_detection(result):
        targets = result.get("targets", [])
        print(f"Detected {len(targets)} targets")
    
    subscription = processed_stream.subscribe(on_detection)
    # ... do work ...
    subscription.dispose()

robot.cleanup()
```

### Custom Processor Pipeline

```python
from dimos.stream.stream_processor import StreamProcessorPipeline, create_processor

# Create custom pipeline
pipeline = StreamProcessorPipeline("custom_pipeline")

# Add processors in sequence
person_processor = create_processor(
    "person_tracking", 
    "person_tracker",
    {"device": "cpu", "confidence_threshold": 0.7}
)

depth_processor = create_processor(
    "depth_estimation",
    "depth_estimator", 
    {"device": "cpu"}
)

pipeline.add_processor(person_processor)
pipeline.add_processor(depth_processor)

# Use with video stream
processed_stream = pipeline.create_stream(video_stream)
```

## Migration Guide

### From Old Implementation

**Before:**
```python
# Hard-coded dependencies
from dimos.perception.person_tracker import PersonTrackingStream
from dimos.perception.object_tracker import ObjectTrackingStream

class UnitreeGo2(Robot):
    def __init__(self):
        # Always loaded, even if not needed
        self.person_tracker = PersonTrackingStream(...)
        self.object_tracker = ObjectTrackingStream(...)
```

**After:**
```python
# Optional, configurable processors
class UnitreeGo2(Robot):
    def __init__(self, stream_processors=None, processor_configs=None):
        if stream_processors:
            self._initialize_stream_processors(stream_processors, processor_configs)
```

### Backward Compatibility

For existing code that expects `person_tracking_stream` or `object_tracking_stream`:

```python
# Legacy access pattern
def get_person_tracking_stream(self):
    """Backward compatibility method."""
    processed_stream = self.get_processed_stream("main")
    if processed_stream:
        return processed_stream.pipe(
            ops.filter(lambda result: "person_tracking" in result.get("processor", ""))
        )
    return None
```

## Benefits

### 1. **CPU Compatibility**
- Robots can run on CPU-only systems
- No mandatory GPU dependencies
- Lightweight model options (e.g., YOLO11n vs YOLO11x)

### 2. **Modular Design**
- Add new AI capabilities without modifying robot classes
- Mix and match processors as needed
- Easy to test individual components

### 3. **Resource Efficiency**
- Only load models that are actually used
- Configure model sizes based on available resources
- Graceful degradation when resources are limited

### 4. **Deployment Flexibility**
- Same codebase works in development (with AI) and production (CPU-only)
- Easy to configure different capabilities per deployment
- Simplified Docker images for different use cases

### 5. **Maintainability**
- Clear separation of concerns
- Easier to update individual AI models
- Better error handling and logging

## Performance Considerations

### CPU vs GPU Configuration

```python
# CPU-optimized configuration
cpu_config = {
    "person_tracking": {
        "device": "cpu",
        "model_path": "yolo11n.pt",  # Smallest model
    },
    "depth_estimation": {
        "device": "cpu",
        "gt_depth_scale": 1000.0
    }
}

# GPU-optimized configuration  
gpu_config = {
    "person_tracking": {
        "device": "cuda",
        "model_path": "yolo11x.pt",  # Largest model
    },
    "depth_estimation": {
        "device": "cuda",
        "gt_depth_scale": 1000.0
    }
}
```

### Memory Management

- Processors are only initialized when first used
- Proper cleanup methods prevent memory leaks
- Configurable batch sizes for processing

## Testing

### Unit Tests

```python
def test_cpu_only_robot():
    """Test robot works without any AI dependencies."""
    robot = UnitreeGo2(disable_video_stream=True)
    assert robot.move_vel(0.1, 0.0, 0.0, 1.0)
    robot.cleanup()

def test_graceful_degradation():
    """Test robot handles missing processors gracefully."""
    robot = UnitreeGo2(
        stream_processors=["nonexistent_processor"],
        processor_configs={}
    )
    # Should not crash, just log warnings
    assert robot.stream_pipeline is None or len(robot.stream_pipeline.processors) == 0
    robot.cleanup()
```

### Integration Tests

```python
def test_processor_pipeline():
    """Test processor pipeline with available processors."""
    available = get_loaded_processors()
    available_names = [name for name, loaded in available.items() if loaded]
    
    if available_names:
        robot = UnitreeGo2(
            stream_processors=available_names[:2],  # Test first 2 available
            processor_configs={name: {"device": "cpu"} for name in available_names[:2]}
        )
        
        assert robot.stream_pipeline is not None
        assert len(robot.stream_pipeline.processors) > 0
        robot.cleanup()
```

## Future Extensions

### 1. Plugin System
- Load processors from external packages
- Runtime processor registration
- Configuration-driven processor loading

### 2. Performance Optimization
- Processor result caching
- Parallel processor execution
- Dynamic processor scheduling

### 3. Cloud Integration
- Remote processor execution
- Model serving via API
- Edge-cloud hybrid processing

## Conclusion

The new modular architecture successfully removes hard-coded model dependencies from robot classes while maintaining full functionality. Robots can now:

- Run on CPU-only systems for basic functionality
- Optionally enable AI capabilities when resources allow
- Scale processing capabilities based on deployment needs
- Maintain clean separation between robot control and AI processing

This design enables more flexible deployments, easier maintenance, and better resource utilization across different environments.
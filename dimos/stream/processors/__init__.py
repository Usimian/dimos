# Copyright 2025 Dimensional Inc.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""Stream processors package.

This package contains optional stream processors that can be loaded dynamically
based on available dependencies. Processors are only imported if their dependencies
are available, allowing the system to run without heavy model dependencies.
"""

import logging
from typing import Dict, Any, Optional

from ..stream_processor import register_processor

logger = logging.getLogger(__name__)


def try_import_processor(module_name: str, class_name: str, processor_name: str) -> bool:
    """Try to import and register a processor if dependencies are available.
    
    Args:
        module_name: Name of the module to import from
        class_name: Name of the class to import
        processor_name: Name to register the processor under
        
    Returns:
        bool: True if processor was successfully imported and registered
    """
    try:
        module = __import__(f"dimos.stream.processors.{module_name}", fromlist=[class_name])
        processor_class = getattr(module, class_name)
        register_processor(processor_name, processor_class)
        logger.info(f"Successfully registered processor: {processor_name}")
        return True
    except ImportError as e:
        logger.debug(f"Could not import processor {processor_name}: {e}")
        return False
    except Exception as e:
        logger.warning(f"Error registering processor {processor_name}: {e}")
        return False


def load_optional_processors() -> Dict[str, bool]:
    """Load all optional processors that have their dependencies available.
    
    Returns:
        Dict mapping processor names to whether they were successfully loaded
    """
    results = {}
    
    # Try to load person tracking processor (requires YOLO)
    results["person_tracking"] = try_import_processor(
        "person_tracking", "PersonTrackingProcessor", "person_tracking"
    )
    
    # Try to load object tracking processor (requires Metric3D)
    results["object_tracking"] = try_import_processor(
        "object_tracking", "ObjectTrackingProcessor", "object_tracking"
    )
    
    # Try to load depth estimation processor (requires Metric3D)
    results["depth_estimation"] = try_import_processor(
        "depth_estimation", "DepthEstimationProcessor", "depth_estimation"
    )
    
    # Try to load semantic segmentation processor (requires FastSAM)
    results["semantic_segmentation"] = try_import_processor(
        "semantic_segmentation", "SemanticSegmentationProcessor", "semantic_segmentation"
    )
    
    # Try to load object detection processor (requires YOLO)
    results["object_detection"] = try_import_processor(
        "object_detection", "ObjectDetectionProcessor", "object_detection"
    )
    
    loaded_count = sum(results.values())
    total_count = len(results)
    logger.info(f"Loaded {loaded_count}/{total_count} optional processors")
    
    return results


# Automatically load processors when package is imported
_loaded_processors = load_optional_processors()


def get_loaded_processors() -> Dict[str, bool]:
    """Get information about which processors were successfully loaded.
    
    Returns:
        Dict mapping processor names to whether they were loaded
    """
    return _loaded_processors.copy()


def is_processor_available(processor_name: str) -> bool:
    """Check if a specific processor is available.
    
    Args:
        processor_name: Name of the processor to check
        
    Returns:
        bool: True if processor is available
    """
    return _loaded_processors.get(processor_name, False)
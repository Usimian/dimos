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

"""
Planning Examples and Interactive Testers

Contains example scripts and interactive testing tools for the manipulation planning stack.

## Examples

- example_worldspec_integration.py: Shows the WorldSpec-based architecture
  with factory functions, context management, and full integration.

## Interactive Testers

```bash
# Full planning tester with robot, obstacles, IK, and motion planning
python -m dimos.manipulation.planning.examples.planning_tester

# Obstacle management tester (syncs with planning tester)
python -m dimos.manipulation.planning.examples.obstacle_tester
```

## Available Commands (Planning Tester)

- **Robot Control**: joints, home, random, ee, collision
- **Planning**: ik, plan
- **Obstacles**: add, move, remove, list, clear
"""

from dimos.manipulation.planning.examples.obstacle_store import ObstacleStore
from dimos.manipulation.planning.examples.planning_tester import PlanningTester

__all__ = ["ObstacleStore", "PlanningTester"]

# Copyright 2026 Dimensional Inc.
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

from dataclasses import dataclass

from reactivex import operators as ops
from reactivex.observable import Observable

from dimos.core import In, Module, ModuleConfig, Out, rpc
from dimos.models.vl.moondream import MoondreamVLModel
from dimos.msgs.sensor_msgs import Image
from dimos.msgs.vision_msgs import Detection2DArray
from dimos.perception.detection.type import ImageDetections2D
from dimos.types.timestamped import align_timestamped
from dimos.utils.reactive import backpressure


@dataclass
class Config(ModuleConfig):
    vlmodel: VlModel = field(default_factory=MoondreamVLModel)


class VisNavSkills(Module[Config]):
    color_image: In[Image]
    detections: In[Detection2DArray]

    default_config = Config

    config: Config
    vlmodel: VlModel

    def __init__(self, **kwargs) -> None:
        super().__init__(**kwargs)
        self.vlmodel = self.config.vlmodel()

    def start(self) -> None:
        self._disposables.add(self.detections_stream().subscribe(print))

    def visual_navigation(self, target: str) -> None:
        self.color_image.observable().pipe(
            ops.map(lambda img: self.vlmodel.query_detections(img, target)),
            ops.filter(lambda d: d.detections_length > 0),
        )

        print(f"Navigating to {target} using visual navigation.")

    # def detections_stream(self) -> Observable[ImageDetections2D]:
    #     return backpressure(
    #         align_timestamped(
    #             self.color_image.pure_observable(),
    #             self.detections.pure_observable().pipe(
    #                 ops.filter(lambda d: d.detections_length > 0)  # type: ignore[attr-defined]
    #             ),
    #             match_tolerance=0.0,
    #             buffer_size=2.0,
    #         ).pipe(
    #             ops.map(
    #                 lambda pair: ImageDetections2D.from_ros_detection2d_array(  # type: ignore[misc]
    #                     *pair
    #                 )
    #             )
    #         )
    #     )


vis_nav_skills = VisNavSkills.blueprint


__all__ = ["VisNavSkills", "vis_nav_skills"]

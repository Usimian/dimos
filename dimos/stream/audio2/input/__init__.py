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

"""Audio input modules."""

from dimos.stream.audio2.input.file import file_input
from dimos.stream.audio2.input.microphone import microphone
from dimos.stream.audio2.input.signal import signal
from dimos.stream.audio2.input.tts_oai import Voice, openai_tts
from dimos.stream.audio2.input.tts_pyttsx3 import pyttsx3_tts

__all__ = ["file_input", "microphone", "signal", "openai_tts", "Voice", "pyttsx3_tts"]

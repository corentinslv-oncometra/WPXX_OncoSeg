"""Print one TotalSegmentator label map. Run with the .venv-totalseg interpreter."""

import json
import sys

from totalsegmentator.map_to_binary import class_map

mapping = class_map[sys.argv[1]]
print(json.dumps({str(key): value for key, value in mapping.items()}))

from game.world import GameWorld
from game import map_print as mp

w = GameWorld()
w.generate_area_around(0, 0)
# walk a bit so map_data is populated
for _ in range(60):
    w.move_player(1, 0)
w.move_player(0, 1)

res = mp.export_map(w, outdir="output", quiet=False)
print("engine =", res["engine"])
import os
for k in ("xlsx", "png"):
    p = res[k]
    print(k, "exists=", os.path.isfile(p), "size=", os.path.getsize(p) if os.path.isfile(p) else 0)

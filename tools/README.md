# tools/build_reel_motion.py

daily-reel スキルの `build_reel.py` と同じ台本JSONで、**動く背景**のリールを作る版。

- 背景：グラデーションのパン＋色相のゆらぎ／ぼかした光の玉がゆっくり流れる／2層の粒子が上昇（奥行き）／斜めの光が横切る
- テロップ：ばねのように弾んで出る（ポップイン）
- 画面上端に進捗バー（あと何秒か分かると最後まで見られやすい）
- シーンごとに任意で `"tag": "経済"` などを付けると、テロップ上にジャンルのラベルが出る

```bash
pip install pyopenjtalk numpy pillow --break-system-packages -q
bash tools/setup_voicevox.sh 20
python3 tools/build_reel_motion.py script.json   # 70秒で約4分
```

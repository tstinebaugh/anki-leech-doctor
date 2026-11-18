# Bundled data sources

The application code in this repository is MIT licensed (see `LICENSE`).
The two kanji datasets below come from third parties and keep their own licenses.
The conversion steps are listed so the files can be reproduced.

## `kanji_ids_data.json`

Ideographic Description Sequences (IDS) for 27,584 CJK characters, used to break
kanji into components for the visual-similarity part of the Collision Radar.

- **Source:** `ids_lv1.txt` from [yi-bai/ids](https://github.com/yi-bai/ids) by Yi Bai,
  commit `2597437` (2026-10-31).
- **License:** **MIT**, Copyright (c) 2021 Yi Bai. Same terms as the MIT text quoted for
  `kanji_similar.json` below.
- **Conversion:** [`scripts/build_kanji_ids.py`](scripts/build_kanji_ids.py) rebuilds the file:
  - keeps CJK Unified Ideographs (U+4E00–U+9FFF) and Extension A (U+3400–U+4DBF);
  - picks the Japanese (`J`) form where one is marked, else the default form;
  - strips variant notes in `()`, `[]` and `{}`, and writes unencoded parts as `#`;
  - keeps the 214 Kangxi radicals (木, 口, 日, ...) whole.

Earlier versions of this repository used CJKVI-IDS (derived from CHISE IDS, GPL-2.0-or-later).
It was replaced so every bundled file is under a permissive license.

## `kanji_similar.json`

Look-alike kanji for 2,902 characters (e.g. 鳥/烏, 日/白, 大/犬), used by the Collision Radar.

- **Source:** [siikamiika/similar-kanji](https://github.com/siikamiika/similar-kanji),
  files `kanji.tgz_similars.ut8` and `book-similars.txt`.
- **License:** **MIT**, Copyright (c) 2017 siikamiika:

  > Permission is hereby granted, free of charge, to any person obtaining a copy of this
  > software and associated documentation files (the "Software"), to deal in the Software
  > without restriction, including without limitation the rights to use, copy, modify,
  > merge, publish, distribute, sublicense, and/or sell copies of the Software, and to
  > permit persons to whom the Software is furnished to do so, subject to the following
  > conditions:
  >
  > The above copyright notice and this permission notice shall be included in all copies
  > or substantial portions of the Software.
  >
  > THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR IMPLIED,
  > INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY, FITNESS FOR A
  > PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE AUTHORS OR COPYRIGHT
  > HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER LIABILITY, WHETHER IN AN ACTION OF
  > CONTRACT, TORT OR OTHERWISE, ARISING FROM, OUT OF OR IN CONNECTION WITH THE SOFTWARE
  > OR THE USE OR OTHER DEALINGS IN THE SOFTWARE.

- **Upstream note:** the similar-kanji project started from `kanji.tgz_similars.ut8` in
  [My JWPce](http://ppcenter.webou.net/my_jwpce/), whose page says its look-alike list was
  taken from kanji.free.fr. `book-similars.txt` has no stated origin. Neither upstream
  states a license.
- **Conversion:** each line of `kanji.tgz_similars.ut8` (`kanji/similar/similar/…/`) and each
  group in `book-similars.txt` was turned into pairs of single characters, made symmetric
  (if A lists B, B lists A), and saved as `{kanji: [sorted look-alikes]}`.

If you maintain one of these datasets and want the attribution changed, please open an issue.

"""Anki bracket-furigana cleanup. Expected outputs follow Anki's furigana filter: a reading
covers everything back to the previous space or '>', and that one space is consumed."""
import pytest

from furigana import clean_sentence_pair, kanji_without_reading, normalize_furigana, to_plain

CASES = [
    # already correct: untouched
    ("来週[らいしゅう]の 社員[しゃいん] 旅行[りょこう]に<b> 参加[さんか]</b>します。",
     "来週[らいしゅう]の 社員[しゃいん] 旅行[りょこう]に<b> 参加[さんか]</b>します。"),
    ("父[ちち]が 他界[たかい]し、<b>肉親[にくしん]</b>は 兄[あに]だけになった。",
     "父[ちち]が 他界[たかい]し、<b>肉親[にくしん]</b>は 兄[あに]だけになった。"),
    ("振[ふ]る 舞[ま]う", "振[ふ]る 舞[ま]う"),
    # missing space: kana or punctuation would join the reading
    ("日本[にほん]の社員[しゃいん]", "日本[にほん]の 社員[しゃいん]"),
    ("彼[かれ]は「本[ほん]」と言[い]った。", "彼[かれ]は「 本[ほん]」と 言[い]った。"),
    ("洗[あら]い物[もの]", "洗[あら]い 物[もの]"),
    # visible spaces removed
    ("友達[ともだち] が 出来[でき]る。", "友達[ともだち]が 出来[でき]る。"),
    ("終[お]わったら、 <b>洗[あら]い 物[もの]</b>をする。", "終[お]わったら、<b>洗[あら]い 物[もの]</b>をする。"),
    ("に <b> 参加[さんか]</b>", "に<b> 参加[さんか]</b>"),
    # space between kanji and bracket, spaces inside brackets, full-width brackets, nbsp
    ("社員 [しゃいん]", "社員[しゃいん]"),
    ("絶[ぜっ ]対[たい]", "絶[ぜっ]対[たい]"),
    ("会社［かいしゃ］に 行[い]く", "会社[かいしゃ]に 行[い]く"),
    ("じゃん&nbsp;拳[けん]", "じゃん 拳[けん]"),
    # okurigana inside the block moves after it
    ("飲む[のむ]のが", "飲[の]むのが"),
    ("新しい[あたらしい] 仲間[なかま]", "新[あたら]しい 仲間[なかま]"),
    ("繰り返す[くりかえす]", "繰り返[くりかえ]す"),
    # kana inside a word's reading stays together
    ("振る舞[ふるま]う", "振る舞[ふるま]う"),
    ("引っ越[ひっこ]す", "引っ越[ひっこ]す"),
    # kana written both before the block and in its reading
    ("お茶[おちゃ]を 飲[の]む", "お 茶[ちゃ]を 飲[の]む"),
    ("これはご飯[ごはん]だ", "これはご 飯[はん]だ"),
    ("やり遂[やりと]げる", "やり 遂[と]げる"),
    ("まだ駄目[だめ]", "まだ 駄目[だめ]"),  # not a duplicate: only a space is needed
    # numbers are part of the word
    ("5日[いつか]", "5日[いつか]"),
    ("台風10号[たいふうじゅうごう]が", "台風10号[たいふうじゅうごう]が"),
    ("このカメラは 500,000[ごじゅうまん] 円[えん]です。", "このカメラは 500,000[ごじゅうまん] 円[えん]です。"),
    ("<b>2、3日[にさんにち]</b>", "<b>2、3日[にさんにち]</b>"),
    # readings with alternatives keep their own spacing and tags
    ("利益[りえき, りやく]が", "利益[りえき, りやく]が"),
    ("が 寂[さび<br>さみ]しい", "が 寂[さび<br>さみ]しい"),
    # spaces between ASCII words are real
    ("Wi-Fi password を 入力[にゅうりょく]して", "Wi-Fi passwordを 入力[にゅうりょく]して"),
    ("", ""),
]


@pytest.mark.parametrize("raw,expected", CASES)
def test_normalize_furigana(raw, expected):
    assert normalize_furigana(raw) == expected


@pytest.mark.parametrize("raw,expected", CASES)
def test_normalize_is_idempotent(raw, expected):
    assert normalize_furigana(expected) == expected


def test_missing_reading_is_left_for_validation():
    # The space is fixed, but a kanji with no reading can't be invented
    assert normalize_furigana("毎日の社員[しゃいん]") == "毎日の 社員[しゃいん]"
    assert kanji_without_reading("毎日の社員[しゃいん]") == "日毎"
    assert kanji_without_reading("振る舞[ふるま]う") == ""
    assert kanji_without_reading("大雨の 時[とき]は") == "大雨"


def test_plain_text_and_pair_cleanup():
    assert to_plain("山道[やまみち]で<b> 避難[ひなん]</b>した。") == "山道で<b>避難</b>した。"
    # The plain sentence is rebuilt from the furigana one, dropping stray readings
    kanji, furi = clean_sentence_pair("山道で避難[ひなん]した。", "山道[やまみち]で 避難[ひなん]した。")
    assert (kanji, furi) == ("山道で避難した。", "山道[やまみち]で 避難[ひなん]した。")
    # Without a furigana sentence, readings are just stripped from the plain one
    assert clean_sentence_pair("山道で 避難[ひなん]した。", "") == ("山道で避難した。", "")


def test_validator_accepts_kana_inside_a_reading_block():
    from gemini_client import validate_persona_sentence
    ok, errors = validate_persona_sentence(
        {"sent_kanji": "彼は<b>振る舞い</b>が上手だ。", "sent_furigana": " 彼[かれ]は<b> 振る舞[ふるま]い</b>が 上手[じょうず]だ。"},
        "振る舞い",
    )
    assert ok, errors


@pytest.mark.anyio
async def test_persona_sentence_spacing_is_fixed_without_a_retry():
    from unittest.mock import patch
    import json
    from gemini_client import GeminiClient

    g = GeminiClient()
    sloppy = {
        "theme_used": "Riding", "sent_kanji": "山道で<b>避難</b>した。",
        "sent_furigana": "山道[やまみち] で<b>避難[ひなん]</b> した。", "sent_eng": "Took refuge.", "rationale": "",
    }
    with patch.object(g, "_call_gemini", return_value=json.dumps(sloppy, ensure_ascii=False)) as call:
        res = await g.generate_personalized_sentence(vocab_kanji="避難", vocab_furigana="ひなん", vocab_def="evacuation")
    assert call.call_count == 1
    assert res["sentFurigana"] == "山道[やまみち]で<b>避難[ひなん]</b>した。"
    assert res["sentKanji"] == "山道で<b>避難</b>した。"


def test_furigana_fields_are_cleaned_when_written_to_anki():
    from unittest.mock import patch
    from anki_client import AnkiClient

    client = AnkiClient()
    info = [{"fields": {"SentKanji": {}, "SentFurigana": {}, "Notes": {}}}]
    with patch.object(client, "invoke", side_effect=[info, None]) as invoke:
        written = client.update_note_by_role(1, {"sentFurigana": "友達[ともだち] が 出来[でき]る", "sentKanji": "友達 が"})
    assert written["SentFurigana"] == "友達[ともだち]が 出来[でき]る"
    assert written["SentKanji"] == "友達 が"  # plain fields are left alone
    assert invoke.call_args_list[1].kwargs["note"]["fields"]["SentFurigana"] == "友達[ともだち]が 出来[でき]る"


def test_extra_bold_words_are_unbolded():
    from gemini_client import keep_target_bold
    raw = "カフェで<b> 猫[ねこ]</b>が<b> 王様[おうさま]</b>のように<b> 振る舞[ふるま]う</b>。"
    assert keep_target_bold(raw, "振る舞う") == "カフェで 猫[ねこ]が 王様[おうさま]のように<b> 振る舞[ふるま]う</b>。"
    # One bold span, or none containing the target: leave it for validation
    assert keep_target_bold("<b> 猫[ねこ]</b>", "犬") == "<b> 猫[ねこ]</b>"
    assert keep_target_bold("<b>ばかり</b>と<b>だけ</b>", "〜ばかり") == "<b>ばかり</b>とだけ"

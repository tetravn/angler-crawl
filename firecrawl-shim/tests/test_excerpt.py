from app import excerpt


def test_query_terms_strips_stopwords_and_dedupes():
    assert excerpt.query_terms("What is the approval rating of Trump approval") == ["approval", "trump"]
    assert excerpt.query_terms("") == []


def test_short_markdown_returned_as_is():
    assert excerpt.relevant_excerpt("short text", ["x"], 1000) == "short text"


def test_surfaces_buried_fact_and_drops_nav():
    nav = "* [Home](https://x.com/home) * [About](https://x.com/about) * [Careers](https://x.com/jobs)"
    filler = "\n\n".join(
        f"Section {i} gives general background unrelated to the topic." for i in range(30))
    fact = "Trump's job approval rating stands at 41% in the latest June 2026 survey."
    md = nav + "\n\n" + filler + "\n\n" + fact
    ex = excerpt.relevant_excerpt(md, excerpt.query_terms("Trump approval rating"), 400)
    assert "41%" in ex            # dữ kiện sâu được kéo lên
    assert "Careers" not in ex    # block nav bị loại
    assert len(ex) <= 400


def test_fallback_to_head_when_nothing_matches():
    md = "lorem ipsum dolor sit amet " * 50
    ex = excerpt.relevant_excerpt(md, ["zzznomatch"], 60)
    assert ex == md[:60]          # không khớp gì → cắt đầu như cũ


def test_wants_numbers():
    assert excerpt.wants_numbers("Trump approval rating in 2026")          # có chữ số
    assert excerpt.wants_numbers("what is the unemployment rate")          # danh từ số liệu
    assert excerpt.wants_numbers("how many seats will Democrats win")      # how many
    assert not excerpt.wants_numbers("who is the president of France")     # không định lượng
    assert not excerpt.wants_numbers("explain the history of jazz")


def test_has_numeric():
    assert excerpt.has_numeric("approval was 40% in June")
    assert excerpt.has_numeric("about 23 seats")
    assert not excerpt.has_numeric("navigation menu home about contact")
    assert not excerpt.has_numeric("a single 5 here")                      # số 1 chữ số → bỏ qua nhiễu


def test_numeric_count_distinguishes_axis_label_from_data():
    assert excerpt.numeric_count("chart axis shows 50%") == 1              # chỉ 1 nhãn → nghèo số liệu
    assert excerpt.numeric_count("approval 38%, disapproval 59% in 2026") == 3
    assert excerpt.numeric_count("no numbers at all here") == 0


def test_prefers_fact_dense_blocks():
    a = "This paragraph is plain prose with no numbers about the subject economy."
    b = "Unemployment fell to 3.8% in 2026 while inflation held at 2.1% according to data."
    md = a + "\n\n" + b + "\n\n" + ("padding sentence here. " * 40)
    ex = excerpt.relevant_excerpt(md, excerpt.query_terms("unemployment inflation rate"), 200)
    assert "3.8%" in ex

from src.importers.wikipedia import parse_event, parse_method

HTML = """<table class="toccolours">
<tr><th colspan="8">Main card (Paramount+)</th></tr>
<tr><th>Weight class</th><th></th><th></th><th></th><th>Method</th><th>Round</th><th>Time</th><th>Notes</th></tr>
<tr><td>Heavyweight</td><td>Ciryl Gane (c)</td><td>def.</td><td>Josh Hokit</td><td>Decision (unanimous) (48–47, 48–47, 48–47)</td><td>5</td><td>5:00</td><td>[a]</td></tr>
<tr><td>Welterweight</td><td>Uroš Medić</td><td>vs.</td><td>Kevin Holland</td><td>Draw (majority) (29–27, 28–28, 28–28)</td><td>3</td><td>5:00</td><td></td></tr>
<tr><th colspan="8">Preliminary card</th></tr>
<tr><td>Catchweight (160.2 lb)</td><td>Terrance McKinney</td><td>def.</td><td>Jim Miller</td><td>TKO (punches)</td><td>1</td><td>1:53</td><td></td></tr>
<tr><td>Lightweight</td><td>A B</td><td>vs.</td><td>C D</td><td>No Contest (accidental eye poke)</td><td>1</td><td>0:40</td><td></td></tr>
</table>"""


def test_parse_method():
    assert parse_method("Decision (split) (29–28, 29–28, 28–29)")[0] == "Decision - Split"
    assert parse_method("Submission (rear-naked choke)")[:2] == ("Submission", "rear-naked choke")
    assert parse_method("TKO (doctor stoppage)")[0] == "TKO - Doctor's Stoppage"
    assert parse_method("KO (punch)")[0] == "KO/TKO"
    assert parse_method("Draw (majority)")[2] == "D"
    assert parse_method("No Contest (overturned)")[2] == "NC"


def test_parse_event():
    f = parse_event(HTML)
    assert len(f) == 4
    assert f[0]["a"] == "Ciryl Gane" and f[0]["title"] and f[0]["kind"] == "W" and f[0]["round"] == 5
    assert f[1]["kind"] == "D"
    assert f[2]["weight_class"] == "Catch Weight" and f[2]["time_sec"] == 113 and f[2]["card"] == "Preliminary card"
    assert f[3]["kind"] == "NC"

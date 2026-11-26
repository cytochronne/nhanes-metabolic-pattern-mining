"""Populate the course's NavyGold PowerPoint template and export its single page."""

from copy import deepcopy
from io import BytesIO
from pathlib import Path
import shutil
import subprocess
from tempfile import TemporaryDirectory
from xml.etree import ElementTree as ET
from xml.dom.minidom import parseString
from zipfile import ZIP_DEFLATED, ZipFile

import xlsxwriter

from .figures import label_itemset


TEMPLATE = (Path("AIAA3111_Poster_Templates_80x100cm") /
            "AIAA3111_Poster_Template_D_NavyGold.pptx")
AUTHOR_LINE = "Yanzhe Xie (50013227)   ·   Ye Guo (50013485)   ·   Che Feng (50013502)"
NS = {
    "a": "http://schemas.openxmlformats.org/drawingml/2006/main",
    "p": "http://schemas.openxmlformats.org/presentationml/2006/main",
    "c": "http://schemas.openxmlformats.org/drawingml/2006/chart",
    "r": "http://schemas.openxmlformats.org/officeDocument/2006/relationships",
}
for prefix, uri in NS.items():
    ET.register_namespace(prefix, uri)

NAVY = "0B2C52"
INK = "1F2933"
MUTED = "42566B"
GOLD = "E9C879"
WHITE = "FFFFFF"
EMU_PER_CM = 360000


def element(parent, tag, **attrs):
    prefix, name = tag.split(":")
    return ET.SubElement(parent, f"{{{NS[prefix]}}}{name}", attrs)


def xml_bytes(root):
    return ET.tostring(root, encoding="utf-8", xml_declaration=True)


def position(shape, x, y, w, h):
    transform = shape.find(".//a:xfrm", NS)
    if transform is None:
        transform = shape.find("p:xfrm", NS)
    transform.find("a:off", NS).attrib.update(x=str(round(x*EMU_PER_CM)), y=str(round(y*EMU_PER_CM)))
    transform.find("a:ext", NS).attrib.update(cx=str(round(w*EMU_PER_CM)), cy=str(round(h*EMU_PER_CM)))


class PosterSlide:
    def __init__(self, content):
        self.root = ET.fromstring(content)
        self.tree = self.root.find("p:cSld/p:spTree", NS)
        self.source = {}
        for shape in list(self.tree)[2:]:
            self.source[shape.find(".//p:cNvPr", NS).get("name")] = shape
            self.tree.remove(shape)
        self.next_id = 150

    def copy(self, source, name=None, bounds=None):
        shape = deepcopy(self.source[source])
        identity = shape.find(".//p:cNvPr", NS)
        identity.set("id", str(self.next_id))
        identity.set("name", name or source)
        self.next_id += 1
        if bounds:
            position(shape, *bounds)
        self.tree.append(shape)
        return shape

    def text(self, name, bounds, content, size, color=INK, bold=False):
        shape = self.copy("TextBox 11", name, bounds)
        body = shape.find("p:txBody", NS)
        body.find("a:bodyPr", NS).set("anchor", "t")
        source_paragraph = body.find("a:p", NS)
        body.remove(source_paragraph)
        for line in content.split("\n"):
            paragraph = deepcopy(source_paragraph)
            paragraph.find(".//a:spcPct", NS).set("val", "102000")
            run = paragraph.find("a:r/a:rPr", NS)
            run.attrib.update(sz=str(round(size*100)), b=str(int(bold)))
            run.find(".//a:srgbClr", NS).set("val", color)
            paragraph.find("a:r/a:t", NS).text = line
            body.append(paragraph)

    def panel(self, title, x, y, w, h):
        self.copy("Rounded Rectangle 10", title + " panel", (x, y, w, h))
        self.text(title, (x+1.45, y+1.1, w-2.9, 2.45), title, 43, NAVY, True)
        self.copy("Rectangle 12", title + " underline", (x+1.5, y+3.75, 4.5, .22))

    def table(self, rows, x, y, widths, heights):
        shape = self.copy("Table 61", "Association rules", (x, y, sum(widths), sum(heights)))
        table = shape.find(".//a:tbl", NS)
        for col, width in zip(table.findall("a:tblGrid/a:gridCol", NS), widths, strict=True):
            col.set("w", str(round(width*EMU_PER_CM)))
        originals = table.findall("a:tr", NS)
        for row in originals:
            table.remove(row)
        for i, (values, height) in enumerate(zip(rows, heights, strict=True)):
            row = deepcopy(originals[0 if i == 0 else 1+(i-1)%2])
            row.set("h", str(round(height*EMU_PER_CM)))
            for j, (cell, value) in enumerate(zip(row.findall("a:tc", NS), values, strict=True)):
                cell.find(".//a:pPr", NS).set("algn", "l" if j == 0 else "ctr")
                cell.find(".//a:rPr", NS).set("sz", "2450")
                cell.find(".//a:t", NS).text = value
                cell.find("a:tcPr", NS).attrib.update(marL="135000", marR="60000")
            table.append(row)


def health_chart(health):
    """Use the same workbook for the editable series and the chart's cached values."""
    buffer = BytesIO()
    with xlsxwriter.Workbook(buffer, {"in_memory": True}) as workbook:
        sheet = workbook.add_worksheet("Health")
        sheet.write_row(0, 0, ["Discovery rule", "All items present", "At least one absent"])
        percent = workbook.add_format({"num_format": "0.0%"})
        for i, row in enumerate(health.itertuples(), 1):
            sheet.write(i, 0, f"R{row.rank}")
            sheet.write_number(i, 1, row.present_proportion, percent)
            sheet.write_number(i, 2, row.absent_proportion, percent)
        chart = workbook.add_chart({"type": "column"})
        for col, color in [(1, NAVY), (2, "C9A24A")]:
            chart.add_series({
                "name": ["Health", 0, col], "categories": ["Health", 1, 0, len(health), 0],
                "values": ["Health", 1, col, len(health), col], "fill": {"color": "#" + color},
                "border": {"none": True}, "gap": 60,
            })
        font = {"name": "Arial", "size": 24, "color": "#" + MUTED}
        chart.set_x_axis({"num_font": font, "line": {"color": "#8494A2"}, "major_tick_mark": "none"})
        chart.set_y_axis({"min": 0, "num_format": "0%", "num_font": font,
                          "major_unit": .10, "major_tick_mark": "none", "line": {"none": True},
                          "major_gridlines": {"visible": True, "line": {"color": "#DCE3E8"}}})
        chart.set_legend({"position": "bottom", "font": font})
        chart.set_chartarea({"border": {"none": True}, "fill": {"color": "#FFFFFF"}})
        chart.set_size({"width": 1230, "height": 550})
        sheet.insert_chart("E2", chart)
    with ZipFile(buffer) as book:
        chart_xml = ET.fromstring(book.read("xl/charts/chart1.xml"))
    chart_xml.remove(chart_xml.find("c:printSettings", NS))
    external = element(chart_xml, "c:externalData", **{f"{{{NS['r']}}}id": "rId1"})
    element(external, "c:autoUpdate", val="0")
    return xml_bytes(chart_xml), buffer.getvalue()


def build_slide(slide, r, authors):
    n, settings = r.n, r.settings["mining"]
    lead = r.candidates.iloc[0]
    health = r.health.set_index("rank").loc[lead["rank"]]
    weighted = r.weighted.loc[r.weighted["rank"].eq(lead["rank"]) &
                              r.weighted.metric.eq("itemset_prevalence")].iloc[0]
    pair = label_itemset(lead.itemset).replace(" + ", " and ").replace("Elevated", "elevated")
    bench = r.benchmark.loc[r.benchmark.n.eq(r.benchmark.n.max())].set_index("algorithm")
    slide.copy("Rectangle 1")
    for name in ("Oval 4", "HKUST(GZ) Logo", "TextBox 6", "TextBox 7", "Rectangle 9"):
        slide.copy(name)
    slide.text("Title", (3, 1.8, 54, 6.9), "Which metabolic abnormalities\noccur together?", 78, WHITE)
    slide.text("Subtitle", (3.1, 9.25, 65, 2), "Association rules and self-rated health in NHANES 2017–2018",
               36, GOLD)
    slide.text("Authors", (3.1, 12.1, 72, 1.8), authors, 29, WHITE)

    slide.panel("Research question and sample", 2.5, 17.4, 36.7, 22.2)
    slide.text("Question", (4, 22.2, 33.7, 5.4),
               "When a routine exam flags more than one measure, which findings tend to appear together? "
               "Do adults with those combinations report poorer health?", 34)
    slide.text("Cohort", (4, 28.3, 33.7, 5.3),
               f"We linked seven U.S. survey files. Of {n['adult_mec']:,} examined adults aged 20 or older, "
               f"{n['adult_mec_complete_items']:,} had all five measures.", 32)
    slide.text("Discovery split", (4, 34.9, 16.4, 2.3), f"{n['discovery']:,} discovery", 42, NAVY, True)
    slide.text("Validation split", (20.9, 34.9, 16.8, 2.3), f"{n['validation']:,} holdout", 42, NAVY, True)
    slide.text("Split design", (4, 37.2, 33.5, 1.6), "Random split by participant", 25, MUTED)

    slide.panel("Pattern mining and validation", 40.7, 17.4, 36.8, 22.2)
    slide.text("Inputs", (42.2, 22.2, 33.8, 4.9),
               "We flagged central obesity, high blood pressure (BP), elevated glycated hemoglobin (HbA1c), "
               "low HDL and high total cholesterol. We kept adults with zero flags.", 31)
    slide.text("Mining criteria", (42.2, 28.1, 33.8, 4.9),
               f"Apriori and FP-Growth searched sets of up to {settings['max_itemset_size']} items. "
               f"Rules needed ≥{settings['min_support']:.0%} support and ≥{settings['min_confidence']:.0%} confidence.", 31)
    slide.text("Validation plan", (42.2, 33.6, 33.8, 5.1),
               f"We ranked sets by excess co-occurrence over independence (leverage), then by count. "
               f"We tested the top {len(r.holdout)} rules in the holdout.", 31)

    slide.panel("Which rules replicated?", 2.5, 41.0, 36.7, 36.8)
    slide.text("Leading support", (4, 45.75, 10.1, 3.55), f"{lead.support:.1%}", 72, NAVY, True)
    slide.text("Leading pair", (14.4, 45.8, 23.25, 5.0),
               f"of discovery adults had both {pair.lower().replace('hba1c', 'HbA1c')} "
               f"({int(lead.joint_n):,}/{int(lead.n):,}).", 30)
    slide.text("Rule key", (4, 51.15, 33.7, 2.8),
               "Ranked by discovery leverage. Leverage is the percentage-point difference between "
               "observed and expected co-occurrence under independence.", 27, MUTED)
    rules = [("Rule", "Discovery leverage (pp)", "Holdout leverage (pp)")]
    for row in r.holdout.itertuples():
        rule = f"{label_itemset(row.antecedent)} → {label_itemset(row.consequent)}"
        rules.append((f"R{row.rank}   {rule}", f"{100 * row.discovery_leverage:+.2f}", f"{100 * row.leverage:+.2f}"))
    heights = [2.25] + [2.5 if len(row[0]) > 41 else 2.03 for row in rules[1:]]
    slide.table(rules, 4, 55.0, [20.35, 6.7, 6.6], heights)
    slide.text("Rule results", (4, 69.3, 33.5, 4.0),
               f"Both miners matched direct counts ({int(r.main_grid.itemsets)} sets, {int(r.main_grid.rules)} rules). "
               f"{int(r.holdout.passes_thresholds.sum())} of {len(r.holdout)} selected rules passed both thresholds in the holdout.", 31)
    slide.text("Timing", (4, 74.0, 33.7, 3.1),
               f"Median time over {int(bench.repetitions.iloc[0])} runs on {n['discovery']:,} adults: "
               f"Apriori {bench.loc['Apriori','median_ms']:.2f} ms, FP-Growth {bench.loc['FP-Growth','median_ms']:.2f} ms.", 27, MUTED)

    slide.panel("Health in the holdout", 40.7, 41.0, 36.8, 36.8)
    slide.text("Health gap", (42.2, 45.75, 33.8, 3.5),
               f"{health.difference_pp:.1f} percentage points", 57, NAVY, True)
    slide.text("Health comparison", (42.2, 49.55, 33.8, 4.6),
               f"For R1, {health.present_proportion:.1%} with both findings "
               f"({int(health.present_fair_or_poor_n)}/{int(health.present_n)}) rated their health fair or poor, versus "
               f"{health.absent_proportion:.1%} of other adults "
               f"({int(health.absent_fair_or_poor_n)}/{int(health.absent_n)}).", 31)
    slide.text("Chart title", (42.2, 55.05, 33.8, 1.8),
               f"Fair or poor self-rated health  ·  n = {n['validation_valid_health']:,}", 29, NAVY, True)
    slide.copy("Chart 60", "Health by rule and pattern membership", (41.75, 57.2, 34.6, 13.7))
    slide.text("Adjusted comparison", (42.2, 71.3, 33.8, 5.3),
               f"For R1, the age- and sex-adjusted odds ratio was {health['or']:.2f} "
               f"(95% CI {health.or_ci_low:.2f}–{health.or_ci_high:.2f}). The interval accounts for survey clustering.", 31)

    slide.panel("Interpretation and limitations", 2.5, 79.2, 75, 13.0)
    slide.text("Weighted prevalence", (4, 84.2, 33.7, 6.7),
               f"Using survey weights, {weighted.proportion:.1%} of adults with complete measures had the leading pair "
               f"(95% CI {weighted.ci_low:.1%}–{weighted.ci_high:.1%}). A follow-up study could test whether "
               "adults with both findings experience later declines in self-rated health.", 30)
    slide.text("Limitations", (42.2, 84.2, 33.6, 6.7),
               "One survey cycle cannot establish which finding came first. Missing measurements may affect "
               "prevalence. Another cycle could test whether these patterns also occur in a different sample.", 30)
    slide.text("Source heading", (3.1, 93.5, 74, 1.7), "Data and references", 31, GOLD, True)
    slide.text("Sources", (3.1, 95.65, 74, 3.5),
               "CDC / NCHS, National Health and Nutrition Examination Survey 2017–2018.\n"
               "Agrawal & Srikant, Fast Algorithms for Mining Association Rules (1994).   Han, Pei & Yin, Mining Frequent Patterns without Candidate Generation (2000).",
               24, WHITE)


def draw_poster(results, path, authors=AUTHOR_LINE):
    converter = shutil.which("libreoffice") or shutil.which("soffice")
    if not converter:
        raise RuntimeError("Install LibreOffice Impress to export the editable poster to PDF.")
    path.parent.mkdir(parents=True, exist_ok=True)
    with TemporaryDirectory(dir=path.parent) as tmp:
        work = Path(tmp).resolve()
        deck = work / path.with_suffix(".pptx").name
        with ZipFile(TEMPLATE) as source, ZipFile(deck, "w", ZIP_DEFLATED) as target:
            slide = PosterSlide(source.read("ppt/slides/slide1.xml"))
            build_slide(slide, results, authors)
            chart, workbook = health_chart(results.health.sort_values("rank"))
            props = parseString(source.read("docProps/core.xml"))
            for tag, value in {"dc:title": "Which metabolic abnormalities occur together?",
                               "dc:creator": authors, "dc:description": "AIAA 3111 course project poster",
                               "cp:lastModifiedBy": authors}.items():
                node = props.getElementsByTagName(tag)[0]
                if node.firstChild:
                    node.removeChild(node.firstChild)
                node.appendChild(props.createTextNode(value))
            rels = parseString(source.read("_rels/.rels"))
            for rel in list(rels.getElementsByTagName("Relationship")):
                if rel.getAttribute("Type").endswith("/thumbnail"):
                    rel.parentNode.removeChild(rel)
            updates = {"ppt/slides/slide1.xml": xml_bytes(slide.root), "ppt/charts/chart1.xml": chart,
                       "docProps/core.xml": props.toxml(encoding="utf-8"), "_rels/.rels": rels.toxml(encoding="utf-8"),
                       "ppt/embeddings/Microsoft_Excel_Sheet1.xlsx": workbook}
            for item in source.infolist():
                if item.filename != "docProps/thumbnail.jpeg":
                    target.writestr(item, updates[item.filename] if item.filename in updates else source.read(item))
        subprocess.run([converter, "-env:UserInstallation=" + (work / "lo").as_uri(), "--headless",
                        "--convert-to", "pdf:impress_pdf_Export", "--outdir", str(work), str(deck)],
                       check=True, capture_output=True, timeout=120)
        rendered = deck.with_suffix(".pdf")
        if not rendered.is_file():
            raise RuntimeError("LibreOffice did not export the poster.")
        deck.replace(path.with_suffix(".pptx"))
        rendered.replace(path)

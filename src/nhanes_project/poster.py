"""Populate the course's PurpleSidebar PowerPoint template and export its single page."""

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
            "AIAA3111_Poster_Template_A_PurpleSidebar.pptx")
AUTHOR_LINE = "Yanzhe Xie (50013227)   ·   Ye Guo (50013485)   ·   Che Feng (50013502)"
NS = {
    "a": "http://schemas.openxmlformats.org/drawingml/2006/main",
    "p": "http://schemas.openxmlformats.org/presentationml/2006/main",
    "c": "http://schemas.openxmlformats.org/drawingml/2006/chart",
    "r": "http://schemas.openxmlformats.org/officeDocument/2006/relationships",
}
for prefix, uri in NS.items():
    ET.register_namespace(prefix, uri)

PURPLE = "671A86"
INK = "2A2A2A"
MUTED = "504858"
EMU_PER_CM = 360000
HEADING_PT = 32
BODY_PT = 26
LABEL_PT = 23


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

    def text(self, name, bounds, content, size, color=INK, bold=False, source="TextBox 55"):
        shape = self.copy(source, name, bounds)
        body = shape.find("p:txBody", NS)
        body.find("a:bodyPr", NS).set("anchor", "t")
        source_paragraph = body.find("a:p", NS)
        for original in body.findall("a:p", NS):
            body.remove(original)
        for line in content.split("\n"):
            paragraph = deepcopy(source_paragraph)
            paragraph.find(".//a:spcPct", NS).set("val", "102000")
            run = paragraph.find("a:r/a:rPr", NS)
            run.attrib.update(sz=str(round(size*100)), b=str(int(bold)))
            run.find(".//a:srgbClr", NS).set("val", color)
            paragraph.find("a:r/a:t", NS).text = line
            body.append(paragraph)

    def picture(self, name, relationship, bounds):
        picture = self.copy("HKUST(GZ) Logo", name, bounds)
        picture.find(".//p:cNvPr", NS).set("descr", name)
        picture.find(".//a:blip", NS).set(f"{{{NS['r']}}}embed", relationship)

    def rectangle(self, name, bounds, color):
        shape = self.copy("Rectangle 53", name, bounds)
        props = shape.find("p:spPr", NS)
        gradient = props.find("a:gradFill", NS)
        fill_index = list(props).index(gradient)
        props.remove(gradient)
        fill = ET.Element(f"{{{NS['a']}}}solidFill")
        element(fill, "a:srgbClr", val=color)
        props.insert(fill_index, fill)

    def table(self, name, rows, x, y, widths, heights, size):
        shape = self.copy("Table 70", name, (x, y, sum(widths), sum(heights)))
        table = shape.find(".//a:tbl", NS)
        grid = table.find("a:tblGrid", NS)
        for extra in list(grid)[len(widths):]:
            grid.remove(extra)
        for col, width in zip(grid, widths, strict=True):
            col.set("w", str(round(width*EMU_PER_CM)))
        originals = table.findall("a:tr", NS)
        for row in originals:
            table.remove(row)
        for i, (values, height) in enumerate(zip(rows, heights, strict=True)):
            row = deepcopy(originals[0 if i == 0 else 1+(i-1)%2])
            row.set("h", str(round(height*EMU_PER_CM)))
            for extra in row.findall("a:tc", NS)[len(widths):]:
                row.remove(extra)
            for j, (cell, value) in enumerate(zip(row.findall("a:tc", NS), values, strict=True)):
                cell.find(".//a:pPr", NS).set("algn", "l" if j == 0 else "ctr")
                cell.find(".//a:rPr", NS).attrib.update(sz=str(round(size*100)), b=str(int(i == 0)))
                fill = cell.find("a:tcPr/a:solidFill/a:srgbClr", NS)
                fill.set("val", "E8DDF0" if i == 0 else ("F5EFF8" if i % 2 else "FAF8FC"))
                cell.find(".//a:t", NS).text = value
                cell.find("a:tcPr", NS).attrib.update(marL="135000", marR="60000")
            table.append(row)


def health_chart(health):
    """Use the same workbook for the editable series and the chart's cached values."""
    buffer = BytesIO()
    with xlsxwriter.Workbook(buffer, {"in_memory": True}) as workbook:
        sheet = workbook.add_worksheet("Health")
        sheet.write_row(0, 0, ["Pattern", "All abnormalities present", "At least one absent"])
        percent = workbook.add_format({"num_format": "0.0%"})
        for i, row in enumerate(health.itertuples(), 1):
            sheet.write(i, 0, f"R{row.rank}")
            sheet.write_number(i, 1, row.present_proportion, percent)
            sheet.write_number(i, 2, row.absent_proportion, percent)
        chart = workbook.add_chart({"type": "column"})
        font = {"name": "Georgia", "size": LABEL_PT, "color": "#" + MUTED}
        for col, color in [(1, PURPLE), (2, "C3A4D3")]:
            chart.add_series({
                "name": ["Health", 0, col], "categories": ["Health", 1, 0, len(health), 0],
                "values": ["Health", 1, col, len(health), col], "fill": {"color": "#" + color},
                "border": {"none": True}, "gap": 50,
                "data_labels": {"value": True, "num_format": "0.0%", "position": "outside_end", "font": font},
            })
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
    # Impress otherwise includes series and category names in each value label.
    for labels in chart_xml.findall(".//c:dLbls", NS):
        index = list(labels).index(labels.find("c:showVal", NS))
        for offset, name in enumerate(("showLegendKey", "showCatName", "showSerName")):
            flag = ET.Element(f"{{{NS['c']}}}{name}", val="0")
            labels.insert(index if offset == 0 else index + offset + 1, flag)
    chart_xml.remove(chart_xml.find("c:printSettings", NS))
    external = element(chart_xml, "c:externalData", **{f"{{{NS['r']}}}id": "rId1"})
    element(external, "c:autoUpdate", val="0")
    return xml_bytes(chart_xml), buffer.getvalue()


def build_slide(slide, r, authors):
    n, settings = r.n, r.settings["mining"]
    lead = r.candidates.iloc[0]
    for name in slide.source:
        number = name.split()[-1]
        if (name == "HKUST(GZ) Logo" or number.isdigit() and
                (int(number) <= 26 or int(number) in
                 {31, 32, 33, 35, 36, 50, 51, 53, 54, 80, 81, 83})):
            slide.copy(name)

    slide.text("Title", (3, 8.55, 59, 8), "Which metabolic abnormalities\noccur together?",
               81, bold=True, source="TextBox 27")
    slide.text("Authors", (3, 16.6, 59, 1.95), authors, 29, source="TextBox 27")
    slide.text("Subtitle", (3, 18.65, 59, 1.85), "Association rules and self-rated health in NHANES 2017–2018",
               BODY_PT, source="TextBox 27")
    slide.text("Course", (63, 11.6, 15, 5), "AIAA 3111\nData Mining", 40, PURPLE, True, source="TextBox 27")

    slide.text("Research question", (2.6, 25, 22.4, 4.2),
               "Which metabolic abnormalities occur together, and how do adults with these patterns rate their health?", BODY_PT, bold=True)
    cohort = [("Sample selection", "Participants"),
              ("Seven files linked", f"{n['merged_demographics']:,}"),
              ("Examined, age 20+", f"{n['adult_mec']:,}"),
              ("All five measures", f"{n['adult_mec_complete_items']:,}"),
              ("Discovery / holdout", f"{n['discovery']:,} / {n['validation']:,}")]
    slide.table("Cohort flow", cohort, 2.6, 29.6, [13.3, 9.3], [1.75]*5, LABEL_PT)
    slide.text("Sample split", (2.6, 39.2, 22.4, 5.8),
               f"We randomly split the {n['adult_mec_complete_items']:,} adults with complete measurements: "
               f"{n['discovery']:,} to find patterns and {n['validation']:,} to test them.", BODY_PT)

    slide.text("Measures", (2.6, 42.9, 22.4, 3.1),
               "Measures covered waist size, blood pressure (BP), HbA1c, HDL and total cholesterol.", BODY_PT)
    slide.text("Mining criteria", (2.6, 49.7, 22.4, 6.9),
               f"Apriori and FP-Growth searched for sets of up to {settings['max_itemset_size']} abnormalities. "
               f"Rules needed ≥{settings['min_support']:.0%} support and ≥{settings['min_confidence']:.0%} confidence. "
               "Adults with no abnormalities counted toward support.", BODY_PT)
    slide.text("Benchmark heading", (2.6, 56.6, 22.4, 2.9), "Median mining time by sample size (ms)", HEADING_PT, PURPLE, True)
    timings = [("Adults", "Apriori", "FP-Growth")]
    for size, group in r.benchmark.groupby("n", sort=True):
        by_name = group.set_index("algorithm")
        timings.append((f"{size:,}", f"{by_name.loc['Apriori', 'median_ms']:.3f}",
                        f"{by_name.loc['FP-Growth', 'median_ms']:.3f}"))
    slide.table("Algorithm benchmark", timings, 2.6, 60.0, [4.3, 9.1, 9.2], [1.7]*len(timings), LABEL_PT)
    slide.text("Timing result", (2.6, 67.6, 22.4, 3.5),
               "FP-Growth was faster than Apriori at all three sample sizes.", BODY_PT)
    slide.text("Mining conclusion", (2.6, 76.1, 22.4, 5.7),
               f"Apriori and FP-Growth found the same {int(r.main_grid.rules)} rules. In the holdout, the five "
               "selected combinations of metabolic abnormalities again occurred more often than expected by chance "
               "under independence.", BODY_PT)
    slide.text("Health conclusion", (2.6, 82.45, 22.4, 4.6),
               "For every combination, adults with all its abnormalities more often rated their health as fair "
               "or poor than adults without the full pattern.", BODY_PT)
    slide.text("Limits", (2.6, 87.8, 22.4, 3.1),
               "The survey measured abnormalities and self-rated health at the same time, limiting causal interpretation.", BODY_PT)

    slide.text("Discovery heading", (28.45, 24.75, 49.4, 2),
               "Which abnormalities occurred together most often?", HEADING_PT, PURPLE, True)
    slide.picture("Discovery co-occurrence heatmap", "rIdHeatmap", (28.25, 26.6, 30.5, 30.5*5/7.8))
    slide.text("Heatmap guide", (59.7, 28.4, 18.45, 6.5),
               "Choose one abnormality on each axis. Their cell shows the percentage of discovery adults who had both. "
               "The diagonal shows how common each abnormality was.", BODY_PT)
    slide.text("Discovery counts", (59.7, 37.2, 18.45, 7.6),
               f"Central obesity and elevated HbA1c were the most common pair. Both occurred in "
               f"{lead.support:.1%} of the discovery sample ({int(lead.joint_n):,} of {int(lead.n):,} adults).", BODY_PT)

    slide.text("Rules heading", (28.45, 45.95, 49.6, 1.6),
               f"Top {len(r.holdout)} association rules", HEADING_PT, PURPLE, True)
    slide.text("Rule comparison", (28.45, 47.55, 49.6, 3.2),
               f"From {int(r.main_grid.itemsets)} frequent sets and {int(r.main_grid.rules)} rules, we selected five patterns by discovery leverage. "
               "All five occurred more often than expected under independence in both samples.", BODY_PT)
    rules = [("Rule", "Lift, discovery", "Lift, holdout", "Discovery leverage (pp)", "Holdout leverage (pp)")]
    for row in r.holdout.itertuples():
        rules.append((f"R{row.rank}   {label_itemset(row.antecedent)} → {label_itemset(row.consequent)}",
                      f"{row.discovery_lift:.3f}", f"{row.lift:.3f}",
                      f"{100*row.discovery_leverage:+.2f}", f"{100*row.leverage:+.2f}"))
    slide.table("Replicated rules", rules, 28.45, 50.25, [22.1, 6.4, 6.3, 7.6, 7.3], [2.0]+[1.55]*len(r.holdout), LABEL_PT)

    strata = r.table("heldout_rule_strata")
    pair = strata.loc[strata.itemset.eq("elevated_bp + elevated_hba1c")]
    if pair.empty:
        pair = strata.loc[strata["rank"].eq(strata["rank"].min())]
    rule = pair.iloc[0]
    slide.text("Age and sex heading", (28.45, 61.1, 49.7, 1.7),
               "Co-occurrence by age and sex", HEADING_PT, PURPLE, True)
    older = pair.loc[pair.age_group.eq("60+")].set_index("sex_code")
    shares = older.joint_n / older.n
    findings = label_itemset(rule.itemset).replace(" + ", " and ").replace("Elevated", "elevated").replace("BP", "blood pressure")
    slide.text("Age and sex description", (28.45, 62.65, 49.7, 2.2),
               f"Bars show the share of each group with {findings} (R{int(rule['rank'])}).\n"
               f"The share was highest at age 60 and over ({shares.loc[1]:.0%} of men and {shares.loc[2]:.0%} of women).",
               BODY_PT)
    slide.rectangle("Age and sex header fill", (28.45, 64.91, 49.7, 1.51), "E8DDF0")
    slide.text("Age groups", (28.82, 65.0, 6.0, 1.35), "Age (years)", LABEL_PT, bold=True)
    columns = [(1, "Men", 35.0), (2, "Women", 57.0)]
    ages = ["20-39", "40-59", "60+"]
    for index, age in enumerate(ages):
        y = 66.65 + 1.68*index
        slide.rectangle(f"{age} row fill", (28.45, y-.15, 49.7, 1.60),
                        "FAF8FC" if index % 2 else "F5EFF8")
        slide.text(age, (28.82, y, 6.0, 1.4), age.replace("-", "–"), LABEL_PT)
    for sex, label, x in columns:
        slide.text(label, (x, 65.0, 19.5, 1.35), label, LABEL_PT, PURPLE, True)
        for index, age in enumerate(ages):
            group = pair.loc[pair.sex_code.eq(sex) & pair.age_group.eq(age)].iloc[0]
            share = group.joint_n / group.n
            y = 66.65 + 1.68*index
            name = f"{label} aged {age}"
            width = 22 * share  # Same zero baseline and scale for all six groups.
            if width > 0:
                slide.rectangle(name, (x, y+.24, width, .76), PURPLE)
            slide.text(name + " prevalence", (x+width+.4, y, 10.8, 1.5),
                       f"{share:.1%}  ({int(group.joint_n)}/{int(group.n)})", LABEL_PT)

    slide.text("Health heading", (28.45, 72.6, 49.4, 1.9),
               "Do adults with these patterns more often report fair or poor health?", HEADING_PT, PURPLE, True)
    slide.text("Health comparison", (28.45, 74.55, 49.6, 2.55),
               "Bars show the percentage rating their health as fair or poor. For each pattern, dark bars show adults "
               "with every abnormality and light bars show those without the full pattern.", BODY_PT)
    slide.copy("Chart 48", "Percentage rating health fair or poor by pattern", (28.45, 77.25, 49.65, 10.65))
    gaps = r.health.difference_pp
    slide.text("Health result", (28.45, 88.2, 49.65, 2.75),
               f"Among {n['validation_valid_health']:,} holdout respondents, fair or poor health was "
               f"{gaps.min():.1f}–{gaps.max():.1f} percentage points more common in adults with the full pattern.", BODY_PT)
    slide.text("References", (16.4, 91.9, 61.8, 5.1),
               "CDC / NCHS. National Health and Nutrition Examination Survey, 2017–2018.\n"
               "Agrawal & Srikant. Fast Algorithms for Mining Association Rules (1994).\n"
               "Han, Pei & Yin. Mining Frequent Patterns without Candidate Generation (2000).", 26)


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
            slide_rels_path = "ppt/slides/_rels/slide1.xml.rels"
            slide_rels = ET.fromstring(source.read(slide_rels_path))
            ET.SubElement(slide_rels, slide_rels[0].tag, Id="rIdHeatmap",
                          Type=NS["r"] + "/image", Target="../media/cooccurrence.png")
            updates[slide_rels_path] = xml_bytes(slide_rels)
            target.write(results.figure("cooccurrence_heatmap"), "ppt/media/cooccurrence.png")
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

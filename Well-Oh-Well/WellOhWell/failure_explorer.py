from collections import Counter
from hashlib import sha256

import duckdb
import streamlit as st

INK = "#252d29"
MISSING = "Unspecified"
PALETTE = ["#287d76", "#c08038", "#527b9d", "#8b7089", "#849454", "#ab6b56", "#8c938e"]


@st.cache_data(show_spinner=False)
def load_failures(path, version):
    with duckdb.connect() as conn:
        return conn.execute("""
            SELECT CAST(failure_start_date AS DATE),
                   COALESCE(NULLIF(TRIM(field_operating_area), ''), 'Unspecified'),
                   COALESCE(NULLIF(TRIM(cause), ''), 'Unspecified'),
                   COALESCE(NULLIF(TRIM(failure_type), ''), 'Unspecified'),
                   COALESCE(NULLIF(TRIM(well_name), ''), ''),
                   regexp_replace(upper(CAST(uwi AS VARCHAR)), '[^A-Z0-9]', '', 'g')
            FROM read_parquet(?)
            WHERE failure_start_date IS NOT NULL
            ORDER BY 1 DESC, 6, 3, 4
        """, [str(path)]).fetchall()


def grouped_labels(counts, limit):
    leaders = [name for name, _ in counts.most_common() if name != MISSING][:limit]
    return {name: name if name in leaders or name == MISSING else "Other categories"
            for name in counts}


def failure_figures(records):
    import plotly.graph_objects as go

    counts = [Counter(row[column] for row in records) for column in (1, 2, 3)]
    groups = [grouped_labels(count, limit) for count, limit in zip(counts, (5, 6, 5))]
    paths = Counter(tuple(group[value] for group, value in zip(groups, row[1:4])) for row in records)
    flows = Counter()
    for path, count in paths.items():
        for stage in (0, 1):
            flows[((stage, path[stage]), (stage + 1, path[stage + 1]))] += count
    nodes = list(dict.fromkeys(node for pair in flows for node in pair))
    positions = {node: index for index, node in enumerate(nodes)}
    cause_colors = {name: PALETTE[i % len(PALETTE)]
                    for i, name in enumerate(dict.fromkeys(groups[1].values()))}

    def link_color(name):
        hex_color = cause_colors[name].lstrip("#")
        red, green, blue = (int(hex_color[i:i + 2], 16) for i in (0, 2, 4))
        return f"rgba({red},{green},{blue},0.4)"

    sankey = go.Figure(go.Sankey(
        arrangement="snap", valueformat=",d",
        node=dict(pad=17, thickness=13, label=[name for _, name in nodes],
                  color=[cause_colors[name] if stage == 1 else "#839d95" for stage, name in nodes],
                  hovertemplate="%{label}<br>%{value:,d} failure records<extra></extra>"),
        link=dict(source=[positions[a] for a, _ in flows], target=[positions[b] for _, b in flows],
                  value=list(flows.values()), color=[link_color((a if a[0] == 1 else b)[1]) for a, b in flows],
                  hovertemplate="%{source.label} → %{target.label}<br>%{value:,d} failure records<extra></extra>"),
    ))
    type_counts = Counter()
    for name, count in counts[2].items():
        type_counts[groups[2][name]] += count
    slices = type_counts.most_common()
    donut = go.Figure(go.Pie(
        labels=[name for name, _ in slices], values=[count for _, count in slices],
        hole=0.68, sort=False, textinfo="none", marker=dict(colors=PALETTE),
        hovertemplate="%{label}<br>%{value:,d} records (%{percent})<extra></extra>",
    ))
    donut.add_annotation(text=f"<b>{len(records):,}</b><br>records", x=0.5, y=0.5,
                         showarrow=False, font=dict(size=16))
    donut.update_layout(legend=dict(orientation="h", y=-0.08, x=0.5, xanchor="center"))
    for figure in (sankey, donut):
        figure.update_layout(height=355, margin=dict(l=8, r=8, t=10, b=12),
                             paper_bgcolor="rgba(0,0,0,0)", font=dict(color=INK, size=12))
    return sankey, donut


def show_failure_explorer(path, cutoff, open_well):
    st.header("Failure Explorer")
    st.caption("Follow recorded failures from operating area to reported cause and failure type.")
    try:
        records = [row for row in load_failures(path, path.stat().st_mtime_ns) if row[0] <= cutoff]
    except (OSError, duckdb.Error) as exc:
        st.error(f"Could not load {path.name}. Check the Datathon folder. ({type(exc).__name__})")
        return
    if not records:
        st.info("No dated failure records are available through this replay date.")
        return

    first = min(row[0] for row in records)
    dates_col, area_col, cause_col = st.columns([1.25, 1, 1])
    dates = dates_col.date_input("Failure date range", (first, cutoff), min_value=first,
                                max_value=cutoff, key=f"failure_dates_{path}_{cutoff}")
    if len(dates) != 2:
        st.info("Select the end of the date range.")
        return
    start, end = dates
    window = [row for row in records if start <= row[0] <= end]
    area = area_col.selectbox("Operating area", [None, *sorted({row[1] for row in window})],
                              format_func=lambda item: item or "All areas")
    area_records = [row for row in window if area is None or row[1] == area]
    cause = cause_col.selectbox("Reported cause", [None, *sorted({row[2] for row in area_records})],
                                format_func=lambda item: item or "All causes")
    filtered = [row for row in area_records if cause is None or row[2] == cause]
    if not filtered:
        st.info("No failure records match these filters.")
        return

    sankey, donut = failure_figures(filtered)
    flow_col, mix_col = st.columns([2.4, 1], gap="medium")
    with flow_col:
        with st.container(border=True):
            st.subheader("Recorded failure paths")
            st.caption("Operating area → Reported cause → Failure type. Band width shows record count.")
            st.plotly_chart(sankey, theme=None, config={"displayModeBar": False})
    with mix_col:
        with st.container(border=True):
            st.subheader("Failure type mix")
            st.caption("Share of filtered records")
            st.plotly_chart(donut, theme=None, config={"displayModeBar": False})

    wells = {}
    for day, area, _, _, name, well in filtered:
        if well:
            entry = wells.setdefault(well, {"Well ID": well, "Well name": name, "Area": area,
                                           "Latest failure": day, "Records": 0})
            entry["Records"] += 1
    st.subheader("Affected wells")
    if not wells:
        st.info("The filtered records have no usable well IDs.")
        return
    st.caption("Select a row and open its production history in Inspect.")
    rows = sorted(wells.values(), key=lambda row: (-row["Records"], row["Well ID"]))
    table_key = sha256(repr(filtered).encode()).hexdigest()[:16]
    selection = st.dataframe(rows, hide_index=True, key=f"failure_wells_{table_key}",
                             on_select="rerun", selection_mode="single-row").selection.rows
    selected = rows[selection[0]]["Well ID"] if selection else None
    st.button("Inspect selected well", disabled=selected is None,
              on_click=open_well, args=(selected,))

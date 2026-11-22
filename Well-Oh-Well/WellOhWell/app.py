import json
import math
import os
from datetime import date, timedelta
from pathlib import Path
from urllib.parse import quote, urlencode

import altair as alt
import pydeck as pdk
import streamlit as st

from backend import (BASE_MARGIN, COSTS, DEMO_DATE, ESTIMATES, REPAIR_TYPES, canary_read,
                     from_parquet, join_inputs, load_csv, optimize, production_drop,
                     verify_scenarios, well_key, well_locations)
from failure_explorer import show_failure_explorer

HERE = Path(__file__).resolve().parent
SAMPLE = HERE / "sample"
TEAM_COSTS = HERE / "data" / "repair_inputs_rod.csv"
REPAIR_PRESETS = {
    "Normal Week": (105_000, 9.7),
    "Tight Week": (73_500, 6.8),
}
desktop = Path.home() / "OneDrive" / "Desktop" / "Datathon"
default_data = desktop if (desktop / "Sam" / "well_estimates.csv").is_file() else HERE.parent
st.set_page_config(page_title="Well, Oh Well", layout="wide")
st.html(HERE / "dashboard.css")
logo_col, title_col = st.columns([1, 10], vertical_alignment="center")

with logo_col:
    st.image(str(HERE / "assets" / "well_oh_well_logo.svg"), width=64)

with title_col:
    st.title("Well, Oh Well")
st.caption("Inspection, repair planning, and historical replay")
mode = st.sidebar.radio("Data mode", ["Sample · synthetic", "Team data"])
sample = mode.startswith("Sample")
directory = Path(st.sidebar.text_input("Datathon folder", str(os.getenv("WOW_DATA", default_data))))
if sample:
    estimates_file, costs_file = SAMPLE / "well_estimates.csv", SAMPLE / "repair_inputs.csv"
    st.info("Sample mode uses synthetic scores, oil readings, and outcomes.")
else:
    estimates_file = directory / "well_estimates.csv"
    if not estimates_file.is_file():
        estimates_file = directory / "Sam" / "well_estimates.csv"
    paths = [directory / "repair_inputs_rod.csv", directory / "Seerat" / "repair_inputs_rod.csv",
             directory / "repair_inputs.csv", directory / "Seerat" / "repair_inputs.csv"]
    costs_file = next((p for p in paths if p.is_file()), TEAM_COSTS)
    st.caption(f"Scores from {estimates_file.name} · Costs from {costs_file.name}")
    if not costs_file.is_file():
        st.warning("Team repair inputs are missing. Inspect and replay are available. "
                   "Add repair_inputs_rod.csv or a matching repair_inputs.csv.")

try:
    estimates = load_csv(estimates_file, ESTIMATES)
    costs = load_csv(costs_file, COSTS) if costs_file.is_file() else []
    dates = sorted({date.fromisoformat(r["as_of_date"]) for r in estimates}, reverse=True)
    if not dates:
        raise ValueError("The estimates file has no dated snapshots.")
    cutoff = st.sidebar.selectbox("Replay date", dates, format_func=date.isoformat)
    active_costs = [r for r in costs if not r.get("as_of_date") or r["as_of_date"] == cutoff.isoformat()]
    rows = join_inputs([r for r in estimates if r["as_of_date"] == cutoff.isoformat()], active_costs)
except (OSError, ValueError) as exc:
    st.error(str(exc))
    st.stop()

ranked = sorted(rows, key=lambda r: (r["failure_risk"] is None, -(r["failure_risk"] or 0)))
wells = list(dict.fromkeys(row["well_id"] for row in ranked))
sections = ["Inspect", "Repair", "Did it work?"] if sample else [
    "Inspect", "Failure Explorer", "Repair", "Did it work?",
]
section = st.sidebar.radio("Section", sections, key="dashboard_section")
source_choice = st.sidebar.radio("Production data", ["Local Parquet", "Canary Read API"]) if not sample else ""
if len(dates) == 1:
    st.sidebar.caption("The estimates file has one scored date. Add dated snapshots for more replay dates.")


@st.cache_data(ttl=60, show_spinner=False)
def cached_history(folder, filename, well, date_field, value_field, first, last, version):
    return from_parquet(folder, filename, well, date_field, value_field, first, last)


def history(filename, well, date_field, value_field, first, last):
    path = directory / filename
    return cached_history(directory, filename, well, date_field, value_field, first, last,
                          path.stat().st_mtime_ns)


def timeline_data(well, first, last):
    if sample:
        index = wells.index(well)
        points = []
        for offset in range((last - first).days + 1):
            day = first + timedelta(days=offset)
            delta = (day - DEMO_DATE).days
            level = 10 + index - (4 if -12 <= delta < 8 else 0)
            points.append((day, round(level + math.sin(delta * 0.2) * 0.8, 2)))
        return points, "Synthetic sample"
    if source_choice == "Canary Read API":
        try:
            tags = json.loads((directory / "canary_tags.json").read_text(encoding="utf-8-sig"))
            points = canary_read(well, first, last, tags)
            if not points:
                raise ValueError("No good-quality readings in this time range.")
            return points, "Canary Read API"
        except (OSError, ValueError, KeyError, TypeError) as exc:
            detail = str(exc) if isinstance(exc, ValueError) else type(exc).__name__
            st.warning(f"Canary unavailable for this selection ({detail}). Trying local team data.")
    try:
        return history("daily_production.parquet", well, "production_date",
                       "oil_produced_m3", first, last), "Local daily_production.parquet"
    except Exception as exc:
        st.error(f"Production history could not be loaded ({type(exc).__name__}).")
        return [], "Unavailable"


def chart(points, source, marker, label):
    st.caption(f"Production source · {source}")
    if not points:
        st.info("No production readings for this well and date range.")
        return
    records = [{"Date": day.isoformat(), "Oil (m³/day)": value} for day, value in points]
    line = alt.Chart(alt.Data(values=records)).mark_line(point=True, color="#236D38").encode(
        x="Date:T", y="Oil (m³/day):Q", tooltip=["Date:T", "Oil (m³/day):Q"])
    event = alt.Chart(alt.Data(values=[{"Date": marker.isoformat(), "Event": label}])).mark_rule(
        color="#625345", strokeDash=[5, 4]).encode(x="Date:T", tooltip=["Date:T", "Event:N"])
    trend = (
        (line + event).properties(height=330)
        .configure_view(strokeOpacity=0)
        .configure_axis(
            labelColor="#3D362D",
            titleColor="#3D362D",
            gridColor="#DEE2DC",
            domainColor="#C5CCC3",
            tickColor="#C5CCC3",
        )
    )
    st.altair_chart(trend, use_container_width=True)


def events(well, first, last, jobs=False):
    if first > last:
        return []
    if sample:
        examples = ([(DEMO_DATE - timedelta(days=20), "Corod Rod Repair")] if jobs else
                    [(DEMO_DATE - timedelta(days=8), "Synthetic repeat"),
                     (DEMO_DATE + timedelta(days=2), "Synthetic failure")])
        return [(day, kind) for day, kind in examples if first <= day <= last]
    name, date_field, value_field = (
        ("well_jobs.parquet", "start_date", "job_type") if jobs else
        ("production_failures.parquet", "failure_start_date", "COALESCE(failure_type, 'Unspecified')")
    )
    try:
        return [(day, kind) for day, kind in history(name, well, date_field, value_field, first, last)
                if not jobs or kind in REPAIR_TYPES]
    except Exception as exc:
        st.warning(f"Recorded events unavailable ({type(exc).__name__}).")
        return None


def percent(value):
    return "—" if value is None else f"{value:.1%}"


def show_events(records, label):
    if records:
        st.dataframe([{"Date": day.isoformat(), label: kind} for day, kind in records], hide_index=True)
    elif records is not None:
        st.caption("No recorded events in this window.")


@st.cache_data(show_spinner=False)
def cached_locations(path, replay_date, version):
    return well_locations(path, replay_date)


def select_chart_well(chart_key, selection_name, widget_key, map_chart=False):
    selection = st.session_state[chart_key]["selection"]
    matches = (selection["objects"].get("well-points", []) if map_chart
               else selection.get(selection_name, []))
    if matches:
        st.session_state[widget_key] = matches[0]["well_id"]


def selected_well_predicate(selection_name):
    return alt.LogicalOrPredicate(**{
        "or": [
            alt.FieldEqualPredicate(field="is_selected", equal=True),
            alt.ParameterPredicate(param=selection_name, empty=False),
        ]
    })


def risk_color(risk):
    if risk >= 0.50:
        return [160, 70, 44, 225]
    if risk >= 0.25:
        return [172, 109, 36, 225]
    return [35, 109, 56, 225]


def inspection_map(records, widget_key, use_basemap):
    latitudes = [r["latitude"] for r in records]
    longitudes = [r["longitude"] for r in records]
    extent = max(max(latitudes) - min(latitudes), max(longitudes) - min(longitudes), 0.02)
    zoom = min(12, max(4, 7.5 - math.log2(extent)))
    layer = pdk.Layer(
        "ScatterplotLayer",
    id="well-points",
    data=records,
    pickable=True,
    auto_highlight=True,
    get_position="[longitude, latitude]",
    get_fill_color="marker_color",
    get_radius="marker_size",
    radius_units="'pixels'",
    radius_min_pixels=4,
    radius_max_pixels=9,
    stroked=True,
    get_line_color=[255, 255, 255],
    line_width_units="'pixels'",
    line_width_min_pixels=1,
    line_width_max_pixels=2,
    )
    deck = pdk.Deck(
        layers=[layer],
        initial_view_state=pdk.ViewState(latitude=(max(latitudes) + min(latitudes)) / 2,
                                         longitude=(max(longitudes) + min(longitudes)) / 2, zoom=zoom),
        map_provider="carto" if use_basemap else None,
        map_style="light" if use_basemap else None,
        tooltip={"text": "#{rank} · {well_id}\n{name}\n{area}\n30-day failure risk: {risk_label}"},
    )
    chart_key = f"{widget_key}_map"
    st.pydeck_chart(deck, height=390, key=chart_key, selection_mode="single-object",
                    on_select=lambda: select_chart_well(chart_key, "", widget_key, map_chart=True))


def offline_inspection_map(records, widget_key):
    selected_well = next((row["well_id"] for row in records if row["is_selected"]), "none")
    selection_name = f"pick_map_well_{selected_well}"
    selected = alt.selection_point(name=selection_name, fields=["well_id"],
                                   toggle=False, clear=False)
    has_selection = any(row["is_selected"] for row in records)
    locations = alt.Chart(alt.Data(values=records)).mark_point(filled=True, stroke="white",
                                                               strokeWidth=1).encode(
        x=alt.X("longitude:Q", title="Longitude",
                scale=alt.Scale(zero=False), axis=alt.Axis(format=".2f")),
        y=alt.Y("latitude:Q", title="Latitude",
                scale=alt.Scale(zero=False), axis=alt.Axis(format=".2f")),
        color=alt.Color("band:N", legend=None,
                        scale=alt.Scale(domain=["50% and above", "25–49%", "Below 25%"],
                                        range=["#A0462C", "#AC6D24", "#236D38"])),
        opacity=alt.condition(
            selected_well_predicate(selection_name),
            alt.value(1.0),
            alt.value(0.4 if has_selection else 1.0),
        ),
        size=alt.Size("marker_size:Q", legend=None, scale=alt.Scale(range=[36, 81])),
        tooltip=[alt.Tooltip("well_id:N", title="Well"),
                 alt.Tooltip("risk:Q", title="30-day failure risk", format=".1%")],
    ).add_params(selected).properties(height=390).configure_view(strokeOpacity=0)
    chart_key = f"{widget_key}_offline_map"
    st.altair_chart(locations, use_container_width=True, key=chart_key,
                    selection_mode=selection_name,
                    on_select=lambda: select_chart_well(chart_key, selection_name, widget_key))


def risk_bars(records, widget_key):
    selected_well = next((row["well_id"] for row in records if row["is_selected"]), "none")
    selection_name = f"pick_well_{selected_well}"
    selected = alt.selection_point(name=selection_name, fields=["well_id"],
                                   toggle=False, clear=False)
    has_selection = any(row["is_selected"] for row in records)
    bars = alt.Chart(alt.Data(values=records)).mark_bar(cornerRadiusEnd=4).encode(
        x=alt.X("risk:Q", title="Predicted failure within 30 days",
                scale=alt.Scale(domain=[0, 1]), axis=alt.Axis(format="%")),
        y=alt.Y("well_id:N", title=None, sort=alt.SortField(field="rank", order="ascending")),
        color=alt.Color("band:N", legend=None,
                        scale=alt.Scale(domain=["50% and above", "25–49%", "Below 25%"],
                                        range=["#A0462C", "#AC6D24", "#236D38"])),
        opacity=alt.condition(
            selected_well_predicate(selection_name),
            alt.value(1.0),
            alt.value(0.4 if has_selection else 1.0),
        ),
        tooltip=[alt.Tooltip("rank:Q", title="Rank"), alt.Tooltip("well_id:N", title="Well"),
                 alt.Tooltip("risk:Q", title="30-day risk", format=".1%"),
                 alt.Tooltip("reason:N", title="Flag reason")],
    ).add_params(selected).properties(height=345).configure_view(strokeOpacity=0)
    chart_key = f"{widget_key}_bars"
    st.altair_chart(bars, use_container_width=True, key=chart_key, selection_mode=selection_name,
                    on_select=lambda: select_chart_well(chart_key, selection_name, widget_key))


DEMO_WELL = "101143404125W300"


def axiom_link(well, end):
    server = os.getenv("WOW_AXIOM_URL", "https://localhost").rstrip("/")
    if well == DEMO_WELL:
        params = {"Application": "Private/Well, Oh Well - Well History"}
    else:
        try:
            mappings = json.loads((directory / "axiom_wells.json").read_text(encoding="utf-8-sig"))
            tags = mappings[well_key(well)]
        except (OSError, ValueError, KeyError, TypeError):
            return
        if not isinstance(tags, list) or not tags or not all(isinstance(tag, str) for tag in tags):
            return
        params = {"chart": "New", "sourcetag[]": tags, "timemode": "Pause",
                  "timeend": f"{end:%m/%d/%Y} 11:59:59 PM", "timeduration": "105d"}
    st.link_button("Open production history in Axiom", f"{server}/#{urlencode(params, doseq=True, quote_via=quote)}")


def open_explorer_well(well):
    st.session_state["pending_explorer_well"] = well
    st.session_state["dashboard_section"] = "Inspect"


if section == "Inspect":
    st.header("Inspect")
    pending_well = st.session_state.pop("pending_explorer_well", None)
    if pending_well:
        st.session_state["inspect_flagged_only"] = False
    flagged = st.toggle("Flagged wells only", key="inspect_flagged_only")
    well_rows = {}
    for row in ranked:
        if not flagged or row["flag_reason"].strip():
            well_rows.setdefault(row["well_id"], row)
    rank_by_id = {well: index for index, well in enumerate(well_rows, 1)}
    top = [dict(rank=rank_by_id[well], well_id=well, risk=row["failure_risk"],
                risk_label=percent(row["failure_risk"]), reason=row["flag_reason"] or "No flag recorded",
                band="50% and above" if row["failure_risk"] >= .5 else
                "25–49%" if row["failure_risk"] >= .25 else "Below 25%")
           for well, row in well_rows.items() if row["failure_risk"] is not None][:10]
    widget_key = f"inspect_well_{mode}_{cutoff}_{flagged}"
    remembered = st.session_state.get(f"last_inspected_well_{sample}")
    requested = pending_well or remembered
    matching_well = next((key for key in well_rows if well_key(key) == well_key(requested)), None)
    extra_well = requested if requested and not matching_well and not flagged and not sample else None
    options = [*well_rows, *([extra_well] if extra_well else [])]
    if options and (pending_well or st.session_state.get(widget_key) not in options):
        st.session_state[widget_key] = matching_well or extra_well or options[0]

    if sample:
        positions = [(53.24, -110.17), (53.29, -110.04), (53.31, -109.97), (53.23, -109.91)]
        locations = {well: {"latitude": lat, "longitude": lon, "name": well, "area": "Synthetic sample"}
                     for well, (lat, lon) in zip(wells, positions)}
    else:
        path = directory / "daily_production.parquet"
        try:
            locations = cached_locations(path, cutoff, path.stat().st_mtime_ns)
        except Exception as exc:
            st.warning(f"Surface locations unavailable ({type(exc).__name__}). You can still use the ranking.")
            locations = {}

    if top:
        st.subheader("Highest predicted failure risk")
        st.caption("Click a pin or a bar to open that well’s details. Map and bars show up to 10 ranked wells.")
        map_column, bars_column = st.columns([1.15, 1], gap="medium")
        current_well = st.session_state[widget_key]
        top = [
            dict(row, is_selected=row["well_id"] == current_well)
            for row in top
        ]
        has_selection = any(row["is_selected"] for row in top)

        mapped = [
            dict(
                row,
                **locations[row["well_id"]],
                marker_color=[
                    *risk_color(row["risk"])[:3],
                    255 if row["is_selected"] or not has_selection else 100,
                ],
                marker_size=9 if row["is_selected"] else 6,
            )
            for row in top
            if row["well_id"] in locations
        ]
        with map_column:
            st.caption("Surface locations · " + ("synthetic demo" if sample else "daily_production.parquet"))
            if mapped:
                with st.expander("Map settings"):
                    use_basemap = st.toggle(
                        "Show street basemap", value=False,
                        help="When off, shows the offline well-location plot without street tiles.",
                    )
                if use_basemap:
                    inspection_map(mapped, widget_key, use_basemap)
                else:
                    st.caption("Offline well locations · click a dot to select a well.")
                    offline_inspection_map(mapped, widget_key)
                st.caption("Risk colors: green below 25%, amber 25% to below 50%, rust 50% and above.")
                if len(mapped) < len(top):
                    st.caption(f"{len(top) - len(mapped)} ranked wells lack valid surface coordinates.")
            else:
                st.info("No ranked wells have usable surface coordinates for this date.")
        with bars_column:
            st.caption("30-day predicted failure probability")
            risk_bars(top, widget_key)

    with st.expander("Full inspection ranking"):
        st.dataframe([{
            "Rank": rank_by_id[well], "Well": well, "30-day failure risk": percent(row["failure_risk"]),
            "Flag reason": row["flag_reason"] or "No flag recorded",
            "Oil lost (m3/day)": row["oil_lost_per_day"],
        } for well, row in well_rows.items()], hide_index=True, use_container_width=True)

    if not sample and not pending_well and st.toggle("Show the imported Canary demo well"):
        st.caption("Well 101143404125W300 is the imported Canary sample. It has no score in the team snapshot.")
        demo_well = DEMO_WELL
        axiom_link(demo_well, DEMO_DATE)
        first, last = DEMO_DATE - timedelta(days=30), DEMO_DATE + timedelta(days=30)
        if not st.checkbox("Show production after the demo date", key="show_demo_well_later"):
            last = DEMO_DATE
        points, source = timeline_data(demo_well, first, last)
        chart(points, source, DEMO_DATE, "Recorded failure / demo date")
    elif options:
        st.subheader("Selected well")
        well = st.selectbox("Well to inspect", options, key=widget_key)
        st.session_state[f"last_inspected_well_{sample}"] = well
        if not sample:
            axiom_link(well, cutoff)
        row = well_rows.get(well)
        if row is None:
            st.caption("This well has historical records. No risk score is available for this replay date.")
            points, source = timeline_data(well, cutoff - timedelta(days=104), cutoff)
            chart(points, source, cutoff, "Replay date")
            st.subheader("Recorded failures through the replay date")
            show_events(events(well, cutoff - timedelta(days=104), cutoff), "Failure type")
            st.stop()
        if well in locations:
            st.caption(f"{locations[well]['name']} · {locations[well]['area']}")
        risk, rank, oil = st.columns(3)
        risk.metric("30-day failure risk", percent(row["failure_risk"]))
        rank.metric("Inspection rank", f"#{rank_by_id[well]}")
        lost = row["oil_lost_per_day"]
        oil.metric("Estimated oil lost", "—" if lost is None else f"{lost:,.2f} m³/day")
        st.write(f"**Flag reason:** {row['flag_reason'] or 'No flag recorded'}")
        points, source = timeline_data(well, cutoff - timedelta(days=104), cutoff)
        chart(points, source, cutoff, "Replay date")
        drop = production_drop(points, cutoff)
        if drop is not None:
            st.metric("Production drop from displayed readings", f"{drop:,.2f} m³/day")
            st.caption("Trailing median vs. last seven calendar days, without the model’s operating-hours filter.")
        if st.checkbox("Reveal later outcomes"):
            st.subheader("Recorded failures in the next 30 days")
            show_events(events(well, cutoff + timedelta(days=1), cutoff + timedelta(days=30)), "Failure type")


elif section == "Failure Explorer":
    show_failure_explorer(directory / "production_failures.parquet", cutoff, open_explorer_well)


elif section == "Repair":
    st.header("Repair")
    scenario = "Custom" if sample else st.radio(
        "Repair scenario", [*REPAIR_PRESETS, "Custom"], horizontal=True, key="repair_scenario"
    )
    budget, crews = ((15_000, 1.0) if sample else
                     REPAIR_PRESETS.get(scenario, REPAIR_PRESETS["Normal Week"]))
    budget_column, crew_column, margin_column = st.columns(3)
    if scenario == "Custom":
        mode_key = "sample" if sample else "team"
        budget = budget_column.number_input("Budget (C$)", min_value=0, value=budget, step=500,
                                            key=f"repair_budget_{mode_key}")
        crews = crew_column.number_input("Crew-days available", min_value=0.0, value=crews, step=0.1,
                                         key=f"repair_crews_{mode_key}")
    else:
        budget_column.caption(f"Budget limit · C${budget:,}")
        crew_column.caption(f"Crew-days available · {crews:g}")
    margin = margin_column.number_input("Oil margin (C$/m³)", min_value=0.0,
                                        value=float(BASE_MARGIN), step=5.0, format="%.6f")
    st.caption("The optimizer can leave budget and crew time unused.")
    missing = [r for r in rows if r["missing"]]
    excluded = [r for r in rows if any(r[k] is None for k in ("repair_cost", "crew_days", "expected_extra_oil"))]
    if missing:
        st.warning(f"{len(missing)} candidates have missing fields. {len(excluded)} are excluded "
                   "because cost, crew-days, or expected oil is missing.")
        with st.expander("See missing fields"):
            st.dataframe([{"Well": r["well_id"], "Job": r["job_type"], "Missing": r["missing"]}
                          for r in missing], hide_index=True)
    try:
        plan = optimize(rows, budget, crews, margin)
    except (ValueError, ImportError) as exc:
        st.error(str(exc))
    else:
        if len(excluded) == len(rows):
            st.info("A team-data repair plan requires matching cost and crew inputs.")
        else:
            spend = sum(r["repair_cost"] for r in plan)
            crew = sum(r["crew_days"] for r in plan)
            gain = sum(r["net_gain"] for r in plan)
            jobs_col, budget_col = st.columns(2)
            crew_col, gain_col = st.columns(2)
            jobs_col.metric("Jobs picked", len(plan))
            budget_col.metric("Budget used", f"C${spend:,.2f}")
            crew_col.metric("Crew-days used", f"{crew:.2f}")
            gain_col.metric("Est. 90-day net gain", f"C${gain:,.2f}")
            st.caption(f"Remaining budget · C${max(0, budget - spend):,.2f}")
            if plan:
                selected_jobs = [
                    {"Well": p["well_id"], "Estimated net gain (C$)": p["net_gain"],
                     "Job": p["job_type"], "Cost (C$)": p["repair_cost"]}
                    for p in plan[:10]
                ]
                st.subheader("Largest contributors to the repair plan")
                gains = alt.Chart(alt.Data(values=selected_jobs)).mark_bar(
                    color="#236D38", cornerRadiusEnd=4).encode(
                    x=alt.X("Estimated net gain (C$):Q", axis=alt.Axis(format="~s")),
                    y=alt.Y("Well:N", title=None, sort="-x"),
                    tooltip=["Well:N", "Job:N",
                             alt.Tooltip("Estimated net gain (C$):Q", format=",.0f"),
                             alt.Tooltip("Cost (C$):Q", format=",.0f")],
                ).properties(height=240).configure_view(strokeOpacity=0)
                st.altair_chart(gains, use_container_width=True)
                st.dataframe([{"Well": p["well_id"], "Job": p["job_type"], "Cost (C$)": p["repair_cost"],
                               "Crew-days": p["crew_days"], "Est. net gain (C$)": round(p["net_gain"], 2)}
                              for p in plan], hide_index=True, use_container_width=True)
            else:
                st.info("No positive-gain job fits the current limits.")
    with st.expander("Business workbook verification"):
        st.dataframe(verify_scenarios(SAMPLE), hide_index=True)
        st.caption("Independent seven-candidate check using Seerat’s worked example.")

else:
    st.header("Did it work?")
    well = st.selectbox("Well", wells)
    reveal = st.checkbox("Reveal outcomes after the replay date")
    ceiling = cutoff + timedelta(days=120) if reveal else cutoff
    repairs = events(well, cutoff - timedelta(days=365), ceiling, jobs=True)
    if repairs:
        repair_day, repair_type = st.selectbox("Recorded rod repair", repairs,
                                               format_func=lambda item: f"{item[0]} · {item[1]}")
        points, source = timeline_data(well, repair_day - timedelta(days=30),
                                       min(ceiling, repair_day + timedelta(days=90)))
        chart(points, source, repair_day, repair_type)
        before = [v for day, v in points if repair_day - timedelta(days=30) <= day < repair_day]
        after = [v for day, v in points if repair_day < day <= repair_day + timedelta(days=30)]
        if before and after:
            st.subheader("Daily oil before and after repair")
            comparison = [{"Period": period, "Mean oil (m³/day)": sum(values) / len(values),
                           "Days observed": len(values)}
                          for period, values in [("Before", before), ("After", after)]]
            summary = alt.Chart(alt.Data(values=comparison)).mark_bar(cornerRadiusEnd=4).encode(
                x=alt.X("Mean oil (m³/day):Q", axis=alt.Axis(tickCount=6)),
                y=alt.Y("Period:N", title=None, sort=["Before", "After"]),
                color=alt.Color("Period:N", legend=None,
                                scale=alt.Scale(domain=["Before", "After"], range=["#837565", "#236D38"])),
                tooltip=["Period:N", alt.Tooltip("Mean oil (m³/day):Q", format=".2f"),
                         "Days observed:Q"],
            ).properties(height=120, autosize=alt.AutoSizeParams(type="fit-x", contains="padding"), padding={"left": 12, "right": 22, "top": 8, "bottom": 8}).configure_view(strokeOpacity=0)
            st.altair_chart(summary, width="stretch", key="repair_oil_comparison")
            st.caption("Observed daily averages within 30 days on each side. The repair day is excluded. "
                       "The after period can be shorter when replay hides later dates.")
        st.subheader("Recorded failures 8–90 days after repair")
        st.caption("This list includes all recorded failure types. The comparable rate below is rod-specific.")
        if ceiling < repair_day + timedelta(days=8):
            st.info("The visible period ends before the repeat-failure window begins.")
        else:
            show_events(events(well, repair_day + timedelta(days=8),
                               min(ceiling, repair_day + timedelta(days=90))), "Failure type")
    elif repairs is not None:
        st.info("No rod repair is recorded for this well in the visible period.")
    st.subheader("Comparable repair estimates at the replay date")
    st.dataframe([{"Candidate repair": r["job_type"], "Repeat-failure rate": percent(r["repeat_failure_rate"]),
                   "Comparable jobs": r["comparable_job_count"], "Expected extra oil (m³)": r["expected_extra_oil"]}
                  for r in rows if r["well_id"] == well], hide_index=True)
    st.caption("Comparable rates describe similar jobs over a 90-day follow-up window.")
st.html("""
<footer class="wow-footer">
    <strong>© 2026 SpaceBar Team · Datathon’26</strong>
    <p>Seerat Dua · Kripansh Rawal · Saptadwipa Mitra · Ishika Ghosh</p>
    <p>All rights reserved by the SpaceBar Team.</p>
</footer>
""")





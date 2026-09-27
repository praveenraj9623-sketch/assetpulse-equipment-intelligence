import streamlit as st

PROJECT = "AssetPulse"
PURPOSE = (
    "Investigate equipment pressure, temperature and operating "
    "patterns using real sensor data."
)

# For the second repository, replace the values above with:
# PROJECT = "EnergyOps"
# PURPOSE = (
#     "Investigate industrial electricity consumption and "
#     "sustained deviations from historical operating patterns."
# )

st.set_page_config(page_title=PROJECT, layout="wide")

st.title(PROJECT)
st.write(PURPOSE)
st.info("Development preview — the analytical application is being built.")

st.subheader("Planned capabilities")
st.markdown("""
- Validated data ingestion and traceable SQL calculations
- Interactive operational dashboards
- Explainable investigation rules
- Downloadable supporting evidence
""")

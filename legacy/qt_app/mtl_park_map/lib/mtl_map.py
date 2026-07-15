from typing import Literal

import folium
from folium.plugins import FastMarkerCluster

# MTL bounding box
MIN_LON, MIN_LAT = -73.97, 45.41  # west, south
MAX_LON, MAX_LAT = -73.48, 45.70  # east, north
DEFAULT_ZOOM = 12

"""
<i class="fa-rotate-0 glyphicon glyphicon-info-sign  icon-white"></i>
<div class="awesome-marker-icon-red awesome-marker leaflet-zoom-animated leaflet-interactive" style="margin-left: -17px; margin-top: -42px; width: 35px; height: 45px; transform: translate3d(627px, 498px, 0px); z-index: 498;" tabindex="0" role="button"><i class="fa-rotate-0 glyphicon glyphicon-info-sign  icon-white"></i></div>
<img src="https://cdn.jsdelivr.net/npm/leaflet@1.9.3/dist/images/marker-icon-2x.png" class="leaflet-marker-icon leaflet-zoom-animated leaflet-interactive" style="margin-left: -12px; margin-top: -41px; width: 25px; height: 41px; opacity: 1; transform: translate3d(822px, 401px, 0px); z-index: 401;" alt="Marker" tabindex="0" role="button">
<path class="leaflet-interactive" stroke="green" stroke-opacity="1" stroke-width="3" stroke-linecap="round" stroke-linejoin="round" fill="green" fill-opacity="0.2" fill-rule="evenodd" d="M1357,467a10,10 0 1,0 20,0 a10,10 0 1,0 -20,0 "></path>
"""

def _add_legend_to_map(m: folium.Map):
    legend_html = """
<div style="
    position: fixed;
    bottom: 30px;
    left: 30px;
    width: 160px;
    background-color: white;
    border:2px solid grey;
    border-radius: 10px;
    z-index:9999;
    font-size:10px;
    padding: 5px;
">
<b>Legend</b><br>
<div style="display:flex; align-items:center;">
    <img src="https://cdn.jsdelivr.net/npm/leaflet@1.9.3/dist/images/marker-icon-2x.png" style="width: 20px; height: 32px; opacity: 1;" alt="Marker" tabindex="0" role="button">
    <span style="margin-left:8px;">Parking Sign</span>
</div>

<div style="display:flex; align-items:center;">
    <svg width="20" height="20">
      <circle cx="10" cy="10" r="8" fill="none" stroke="green" stroke-width="3"/>
    </svg>
    <span style="margin-left:8px;">Parking Spot (Free)</span>
</div>

<div style="display:flex; align-items:center;">
    <svg width="20" height="20">
      <circle cx="10" cy="10" r="8" fill="none" stroke="orange" stroke-width="3"/>
    </svg>
    <span style="margin-left:8px;">Parking Spot (Paid)</span>
</div>

</div>
"""
    m.get_root().html.add_child(folium.Element(legend_html))

def mtl_map(
    min_lon: float = MIN_LON,
    max_lon: float = MAX_LON,
    min_lat: float = MIN_LAT,
    max_lat: float = MAX_LAT,
    zoom: int = DEFAULT_ZOOM,
) -> folium.Map:
    m = folium.Map(
        location=[(min_lat + max_lat) / 2, (min_lon + max_lon) / 2],
        zoom_start=zoom,
        max_bounds=True,
    )
    m.fit_bounds([[min_lat, min_lon], [max_lat, max_lon]])
    map_name = m.get_name()
    m.get_root().html.add_child(
        folium.Element(f"""
                <script src="qrc:///qtwebchannel/qwebchannel.js"></script>
                <script>
                    console.log('Loading map');
                    document.addEventListener("DOMContentLoaded", function() {{

                        new QWebChannel(qt.webChannelTransport, function(channel) {{
                            var bridge = channel.objects.bridge;

                            function reportBounds() {{
                                var b ={map_name}.getBounds();
                                var z = {map_name}.getZoom();
                                bridge.update_data(
                                    b.getNorth(),
                                    b.getSouth(),
                                    b.getEast(),
                                    b.getWest(),
                                    z
                                );
                            }}

                            // Trigger when the map finishes moving or zooming
                            {map_name}.on('moveend', reportBounds);

                            // Also send initial bounds after first load
                            setTimeout(reportBounds, 500);
                        }});

                    }});
                </script>
            """)
    )
    _add_legend_to_map(m)
    return m


def add_marker(m: folium.Map, lat: float, lon: float, popup: str, color: str):
    icon = folium.Icon(color=color)
    folium.Marker(
        location=[lat, lon],
        icon=icon,
        popup=popup,
    ).add_to(m)


def add_marker_cluster(
    m: folium.Map,
    points: list[tuple[float, float, str]],
    type_: Literal["marker", "circleMarker"] = "marker",
    color: str | None = None,
):
    FastMarkerCluster(
        data=points,
        callback=f"""
        function(row) {{
            var marker = L.{type_}(
                new L.LatLng(row[0], row[1]),
                {f'{{color: "{color}"}}' if color else ''}
            );
            marker.bindPopup(row[2]);
            return marker;
        }}
    """,
        disableClusteringAtZoom=17,
    ).add_to(m)


# def mtl_map_html(
#     min_lon: float = MIN_LON,
#     max_lon: float = MAX_LON,
#     min_lat: float = MIN_LAT,
#     max_lat: float = MAX_LAT,
#     zoom: int = DEFAULT_ZOOM,
# ) -> str:
#     return mtl_map(min_lon, max_lon, min_lat, max_lat, zoom).get_root().render()
#
#
# def mtl_map_html_with_markers(
#     *markers_list: list[tuple[float, float, str]],
#     min_lon: float = MIN_LON,
#     max_lon: float = MAX_LON,
#     min_lat: float = MIN_LAT,
#     max_lat: float = MAX_LAT,
#     zoom: int = DEFAULT_ZOOM,
# ) -> str:
#     m = mtl_map(min_lon, max_lon, min_lat, max_lat, zoom)
#     for markers in markers_list:
#         FastMarkerCluster(
#             data=markers,
#             callback="""
#             function(row) {
#                 var marker = L.marker(new L.LatLng(row[0], row[1]));
#                 marker.bindPopup(row[2]);
#                 return marker;
#             }
#         """,
#             disableClusteringAtZoom=17,
#     ).add_to(m)
#     return m.get_root().render()

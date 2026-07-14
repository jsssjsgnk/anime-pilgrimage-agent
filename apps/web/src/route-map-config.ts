import maplibregl from "maplibre-gl";

export const ROUTE_MAP_STYLE_URL = "https://tiles.openfreemap.org/styles/liberty";

export function createRouteMapOptions(
  container: HTMLDivElement,
  bounds: maplibregl.LngLatBounds,
): maplibregl.MapOptions {
  return {
    container,
    style: ROUTE_MAP_STYLE_URL,
    bounds,
    fitBoundsOptions: { padding: 56, maxZoom: 15 },
    // The official style supplies OpenFreeMap, OpenMapTiles, and OpenStreetMap attribution.
    attributionControl: {
      compact: false,
    },
    interactive: true,
    cooperativeGestures: true,
    pitchWithRotate: false,
    dragRotate: false,
    locale: {
      "Map.Title": "Route A 交互式地图",
      "NavigationControl.ZoomIn": "放大地图",
      "NavigationControl.ZoomOut": "缩小地图",
      "NavigationControl.ResetBearing": "重置地图方向",
      "FullscreenControl.Enter": "全屏查看地图",
      "FullscreenControl.Exit": "退出地图全屏",
      "AttributionControl.ToggleAttribution": "显示地图署名",
      "CooperativeGesturesHandler.WindowsHelpText": "按住 Ctrl 并滚动以缩放地图",
      "CooperativeGesturesHandler.MacHelpText": "按住 Command 并滚动以缩放地图",
      "CooperativeGesturesHandler.MobileHelpText": "使用双指移动或缩放地图",
    },
  };
}

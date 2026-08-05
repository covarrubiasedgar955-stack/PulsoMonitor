"use client";

import { useEffect, useRef, useState } from "react";
import type { LayerGroup, LeafletMouseEvent, Map as LeafletMap } from "leaflet";
import type { MapIncident } from "@/types/news";

const TEQUILA_CENTER: [number, number] = [20.8817, -103.8356];

export interface MapPosition {
  latitude: number;
  longitude: number;
}

function markerTone(incident: MapIncident) {
  if (incident.priority === "Urgente") return "urgent";
  if (incident.status === "Publicada") return "published";
  if (incident.status === "Programada") return "scheduled";
  if (incident.status === "En revisión") return "review";
  return "pending";
}

export default function IncidentMap({
  incidents,
  selectedId,
  onSelect,
  picking = false,
  preview = null,
  onMapClick,
  compact = false,
}: {
  incidents: MapIncident[];
  selectedId?: number | null;
  onSelect?: (id: number) => void;
  picking?: boolean;
  preview?: MapPosition | null;
  onMapClick?: (position: MapPosition) => void;
  compact?: boolean;
}) {
  const containerRef = useRef<HTMLDivElement | null>(null);
  const [ready, setReady] = useState(false);
  const mapRef = useRef<LeafletMap | null>(null);
  const markerLayerRef = useRef<LayerGroup | null>(null);
  const previewLayerRef = useRef<LayerGroup | null>(null);
  const onSelectRef = useRef(onSelect);
  const onMapClickRef = useRef(onMapClick);
  const pickingRef = useRef(picking);

  useEffect(() => {
    onSelectRef.current = onSelect;
    onMapClickRef.current = onMapClick;
    pickingRef.current = picking;
  }, [onMapClick, onSelect, picking]);

  useEffect(() => {
    let cancelled = false;
    let resizeTimer: number | undefined;

    void import("leaflet").then((L) => {
      if (cancelled || !containerRef.current || mapRef.current) return;
      const map = L.map(containerRef.current, { zoomControl: true }).setView(TEQUILA_CENTER, compact ? 14 : 13);
      L.tileLayer("https://tile.openstreetmap.org/{z}/{x}/{y}.png", {
        maxZoom: 19,
        attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors',
      }).addTo(map);
      markerLayerRef.current = L.layerGroup().addTo(map);
      previewLayerRef.current = L.layerGroup().addTo(map);
      map.on("click", (event: LeafletMouseEvent) => {
        if (!pickingRef.current) return;
        onMapClickRef.current?.({ latitude: event.latlng.lat, longitude: event.latlng.lng });
      });
      mapRef.current = map;
      setReady(true);
      resizeTimer = window.setTimeout(() => map.invalidateSize(), 100);
    });

    return () => {
      cancelled = true;
      if (resizeTimer) window.clearTimeout(resizeTimer);
      mapRef.current?.remove();
      mapRef.current = null;
      markerLayerRef.current = null;
      previewLayerRef.current = null;
    };
  }, [compact]);

  useEffect(() => {
    let cancelled = false;
    void import("leaflet").then((L) => {
      if (cancelled || !ready || !markerLayerRef.current) return;
      markerLayerRef.current.clearLayers();
      incidents.forEach((incident) => {
        const tone = markerTone(incident);
        const selected = incident.id === selectedId ? " selected" : "";
        const icon = L.divIcon({
          className: "incident-div-icon",
          html: `<span class="incident-marker-core ${tone}${selected}"><i></i></span>`,
          iconSize: [30, 36],
          iconAnchor: [15, 34],
        });
        const marker = L.marker([incident.latitude, incident.longitude], { icon, keyboard: true });
        const tooltip = document.createElement("span");
        tooltip.textContent = incident.title;
        marker.bindTooltip(tooltip, { direction: "top", offset: [0, -25] });
        marker.on("click", () => onSelectRef.current?.(incident.id));
        marker.addTo(markerLayerRef.current as LayerGroup);
      });
    });
    return () => { cancelled = true; };
  }, [incidents, ready, selectedId]);

  useEffect(() => {
    let cancelled = false;
    void import("leaflet").then((L) => {
      if (cancelled || !ready || !previewLayerRef.current) return;
      previewLayerRef.current.clearLayers();
      if (!preview) return;
      L.circleMarker([preview.latitude, preview.longitude], {
        radius: 10,
        color: "#ffffff",
        weight: 4,
        fillColor: "#2463eb",
        fillOpacity: 1,
      }).addTo(previewLayerRef.current);
      mapRef.current?.setView([preview.latitude, preview.longitude], Math.max(mapRef.current.getZoom(), 16));
    });
    return () => { cancelled = true; };
  }, [preview, ready]);

  useEffect(() => {
    const selected = incidents.find((item) => item.id === selectedId);
    if (ready && selected && mapRef.current) {
      mapRef.current.flyTo([selected.latitude, selected.longitude], Math.max(mapRef.current.getZoom(), 15), { duration: .6 });
    }
  }, [incidents, ready, selectedId]);

  return <div ref={containerRef} className={`incident-map ${picking ? "picking" : ""} ${compact ? "compact" : ""}`} aria-label="Mapa interactivo de incidencias" />;
}

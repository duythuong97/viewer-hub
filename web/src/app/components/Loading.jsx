import React from "react";

export function Skeleton({ lines = 3, height = 16, className = "" }) {
  return (
    <div className={`vh-skeleton-wrap ${className}`} aria-busy="true">
      {Array.from({ length: lines }).map((_, i) => (
        <div
          key={i}
          className="vh-skeleton-line"
          style={{ height, width: i === lines - 1 && lines > 1 ? "60%" : "100%" }}
        />
      ))}
    </div>
  );
}

export function ActionSpinner({ loading, label, loadingLabel = "Đang xử lý..." }) {
  return (
    <span style={{ display: "inline-flex", alignItems: "center", gap: 6 }}>
      {loading && <md-circular-progress indeterminate style={{ width: 14, height: 14 }} />}
      <span>{loading ? loadingLabel : label}</span>
    </span>
  );
}

import React from "react";
import { useTitle } from "../context.jsx";
import { LinkButton } from "../ui.jsx";

export default function NotFound() {
  useTitle("Không tìm thấy");
  return <div className="md-empty">
    <md-icon>search_off</md-icon><h2>Không tìm thấy</h2><p>Trang này không tồn tại.</p>
    <LinkButton to="/" icon="home">Về trang chủ</LinkButton>
  </div>;
}

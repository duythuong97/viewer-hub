// CSV: /csv opens the last viewed dataset (?manage=1: the list), /csv/<id> searches one. API: viewer_hub/csv/routes.py.
import React, { useEffect } from "react";
import { http } from "../../app/http.js";
import { useQuery, useRouter } from "../../app/router.jsx";
import { useLoad } from "../../app/ui.jsx";
import DatasetPage from "./DatasetPage.jsx";
import ListPage from "./ListPage.jsx";

export const API = "/csv/api/datasets";

export default function CsvPage({ subpath }) {
  const id = subpath.split("/").filter(Boolean)[0];
  return id ? <DatasetPage id={decodeURIComponent(id)} /> : <Start />;
}

function Start() {
  const [query] = useQuery();
  const { navigate } = useRouter();
  const { data, reload } = useLoad(() => http.get(API));
  const open = data && data.last && !query.manage && !query.describe;
  useEffect(() => { if (open) navigate(`/csv/${encodeURIComponent(data.last)}`, { replace: true }); }, [open]);
  if (!data || open) return null;
  return <ListPage datasets={data.datasets} reload={reload} />;
}

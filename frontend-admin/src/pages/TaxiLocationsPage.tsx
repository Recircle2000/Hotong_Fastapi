import { FormEvent, useEffect, useState } from "react";

import { AdminModal } from "../components/AdminModal";
import { AdminShell } from "../components/AdminShell";
import { useDocumentTitle } from "../hooks/useDocumentTitle";
import {
  ApiError,
  createAdminTaxiLocation,
  deleteAdminTaxiLocation,
  getAdminAppSettings,
  getAdminTaxiLocations,
  updateAdminTaxiEnabled,
  updateAdminTaxiLocation,
} from "../lib/api";
import type {
  AdminAppSettings,
  AdminTaxiLocation,
  AdminTaxiLocationPayload,
  TaxiLocationCategory,
} from "../lib/types";
import { useToast } from "../toast/ToastProvider";

const emptyForm: AdminTaxiLocationPayload = {
  name: "",
  category: "other",
  sort_order: 0,
  is_active: true,
};

const categoryLabels: Record<TaxiLocationCategory, string> = {
  campus: "캠퍼스",
  station: "역",
  terminal: "터미널",
  other: "기타",
};

function TaxiServiceSwitch() {
  const { showToast } = useToast();
  const [settings, setSettings] = useState<AdminAppSettings | null>(null);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    getAdminAppSettings()
      .then(setSettings)
      .catch((reason) => setError(reason instanceof ApiError ? reason.message : "운영 상태를 불러오지 못했습니다."));
  }, []);

  async function toggle() {
    if (!settings) return;
    const next = !settings.taxi_enabled;
    const message = next
      ? "택시 서비스를 켤까요? 앱 홈 화면에 택시 메뉴가 다시 나타나고 새 팟을 만들 수 있게 됩니다."
      : "택시 서비스를 끌까요? 새 팟 생성과 참여가 막히고 홈 화면에서 택시 메뉴가 사라집니다.\n진행 중인 팟의 참여자는 채팅과 나가기를 계속 이용할 수 있습니다.";
    if (!window.confirm(message)) return;
    setSaving(true);
    try {
      setSettings(await updateAdminTaxiEnabled(next));
      showToast(next ? "택시 서비스를 켰습니다." : "택시 서비스를 껐습니다.", "success");
    } catch (reason) {
      showToast(reason instanceof ApiError ? reason.message : "운영 상태를 바꾸지 못했습니다.", "error");
    } finally {
      setSaving(false);
    }
  }

  const enabled = settings?.taxi_enabled ?? false;
  const updatedAt = settings?.taxi_updated_at ? new Date(settings.taxi_updated_at).toLocaleString("ko-KR") : null;

  return (
    <section className="mb-6 flex flex-wrap items-center justify-between gap-4 rounded-2xl border border-slate-200 bg-white p-5 shadow-sm">
      <div>
        <div className="flex items-center gap-2">
          <h2 className="text-base font-semibold text-slate-900">택시 서비스 운영</h2>
          {settings ? (
            <span className={`rounded-full px-2.5 py-0.5 text-xs font-semibold ${enabled ? "bg-emerald-50 text-emerald-700" : "bg-slate-100 text-slate-600"}`}>
              {enabled ? "운영 중" : "중지됨"}
            </span>
          ) : null}
        </div>
        <p className="mt-1 text-sm text-slate-500">
          끄면 앱 홈의 택시 메뉴가 사라지고 새 팟 생성·참여가 막힙니다. 진행 중인 팟 참여자는 계속 이용할 수 있습니다.
        </p>
        {error ? <p className="mt-1 text-sm text-rose-600">{error}</p> : null}
        {updatedAt ? <p className="mt-1 text-xs text-slate-400">마지막 변경: {updatedAt}</p> : null}
      </div>
      <button
        type="button"
        role="switch"
        aria-checked={enabled}
        aria-label="택시 서비스 운영"
        disabled={!settings || saving}
        onClick={() => void toggle()}
        className={`relative inline-flex h-7 w-12 shrink-0 items-center rounded-full transition-colors disabled:opacity-50 ${enabled ? "bg-emerald-500" : "bg-slate-300"}`}
      >
        <span className={`inline-block h-5 w-5 rounded-full bg-white shadow transition-transform ${enabled ? "translate-x-6" : "translate-x-1"}`} />
      </button>
    </section>
  );
}

export function TaxiLocationsPage() {
  useDocumentTitle("택시 거점 관리");
  const { showToast } = useToast();
  const [items, setItems] = useState<AdminTaxiLocation[]>([]);
  const [loading, setLoading] = useState(true);
  const [editing, setEditing] = useState<AdminTaxiLocation | null>(null);
  const [form, setForm] = useState<AdminTaxiLocationPayload>(emptyForm);
  const [open, setOpen] = useState(false);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function load() {
    setLoading(true);
    setError(null);
    try {
      setItems(await getAdminTaxiLocations());
    } catch (reason) {
      setError(reason instanceof ApiError ? reason.message : "택시 거점을 불러오지 못했습니다.");
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => { void load(); }, []);

  function showCreate() {
    setEditing(null);
    setForm(emptyForm);
    setOpen(true);
  }

  function showEdit(item: AdminTaxiLocation) {
    setEditing(item);
    setForm({ name: item.name, category: item.category, sort_order: item.sort_order, is_active: item.is_active });
    setOpen(true);
  }

  async function submit(event: FormEvent) {
    event.preventDefault();
    setSaving(true);
    try {
      if (editing) await updateAdminTaxiLocation(editing.id, form);
      else await createAdminTaxiLocation(form);
      showToast(editing ? "택시 거점을 수정했습니다." : "택시 거점을 등록했습니다.", "success");
      setOpen(false);
      await load();
    } catch (reason) {
      showToast(reason instanceof ApiError ? reason.message : "저장하지 못했습니다.", "error");
    } finally {
      setSaving(false);
    }
  }

  async function remove(item: AdminTaxiLocation) {
    if (!window.confirm(`"${item.name}" 거점을 삭제하시겠습니까?`)) return;
    try {
      await deleteAdminTaxiLocation(item.id);
      showToast("택시 거점을 삭제했습니다.", "success");
      await load();
    } catch (reason) {
      showToast(reason instanceof ApiError ? reason.message : "삭제하지 못했습니다.", "error");
    }
  }

  return (
    <AdminShell
      title="택시 거점 관리"
      description="사용자가 택시팟 출발지와 도착지로 선택할 거점을 관리합니다."
      actions={<button type="button" onClick={showCreate} className="rounded-lg bg-blue-600 px-4 py-2 text-sm font-semibold text-white">새 거점</button>}
    >
      <TaxiServiceSwitch />
      {error ? <div className="mb-4 rounded-lg border border-rose-200 bg-rose-50 p-4 text-sm text-rose-700">{error}</div> : null}
      <section className="overflow-hidden rounded-2xl border border-slate-200 bg-white shadow-sm">
        {loading ? <div className="p-8 text-sm text-slate-500">불러오는 중입니다.</div> : items.length === 0 ? (
          <div className="p-8 text-sm text-slate-500">등록된 택시 거점이 없습니다.</div>
        ) : (
          <div className="overflow-x-auto">
            <table className="min-w-full text-left text-sm">
              <thead className="bg-slate-50 text-slate-600"><tr><th className="px-5 py-3">순서</th><th className="px-5 py-3">이름</th><th className="px-5 py-3">분류</th><th className="px-5 py-3">상태</th><th className="px-5 py-3">관리</th></tr></thead>
              <tbody>{items.map((item) => (
                <tr key={item.id} className="border-t border-slate-200">
                  <td className="px-5 py-4">{item.sort_order}</td>
                  <td className="px-5 py-4 font-medium">{item.name}</td>
                  <td className="px-5 py-4">{categoryLabels[item.category]}</td>
                  <td className="px-5 py-4">{item.is_active ? "사용 중" : "비활성"}</td>
                  <td className="px-5 py-4"><div className="flex gap-2"><button onClick={() => showEdit(item)} className="rounded border px-3 py-1">수정</button><button onClick={() => void remove(item)} className="rounded border border-rose-200 px-3 py-1 text-rose-700">삭제</button></div></td>
                </tr>
              ))}</tbody>
            </table>
          </div>
        )}
      </section>

      {open ? (
        <AdminModal title={editing ? "택시 거점 수정" : "택시 거점 등록"} onClose={() => setOpen(false)}>
          <form onSubmit={submit} className="space-y-4">
            <label className="block text-sm font-medium">이름<input required maxLength={80} value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} className="mt-2 w-full rounded-lg border border-slate-300 px-3 py-2" /></label>
            <label className="block text-sm font-medium">분류<select value={form.category} onChange={(e) => setForm({ ...form, category: e.target.value as TaxiLocationCategory })} className="mt-2 w-full rounded-lg border border-slate-300 px-3 py-2">{Object.entries(categoryLabels).map(([value, label]) => <option key={value} value={value}>{label}</option>)}</select></label>
            <label className="block text-sm font-medium">정렬 순서<input type="number" min={0} max={10000} value={form.sort_order} onChange={(e) => setForm({ ...form, sort_order: Number(e.target.value) })} className="mt-2 w-full rounded-lg border border-slate-300 px-3 py-2" /></label>
            <label className="flex items-center gap-2 text-sm"><input type="checkbox" checked={form.is_active} onChange={(e) => setForm({ ...form, is_active: e.target.checked })} />사용자 선택 목록에 표시</label>
            <button disabled={saving || !form.name.trim()} className="w-full rounded-lg bg-blue-600 px-4 py-3 font-semibold text-white disabled:bg-blue-300">{saving ? "저장 중..." : "저장"}</button>
          </form>
        </AdminModal>
      ) : null}
    </AdminShell>
  );
}

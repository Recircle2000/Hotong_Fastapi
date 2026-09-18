import { FormEvent, useEffect, useState } from "react";

import { AdminModal } from "../components/AdminModal";
import { AdminShell } from "../components/AdminShell";
import { useDocumentTitle } from "../hooks/useDocumentTitle";
import {
  ApiError,
  createAdminTaxiLocation,
  deleteAdminTaxiLocation,
  getAdminTaxiLocations,
  updateAdminTaxiLocation,
} from "../lib/api";
import type { AdminTaxiLocation, AdminTaxiLocationPayload, TaxiLocationCategory } from "../lib/types";
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

import { useEffect, useState } from "react";

import { createLabel, deleteLabel, listLabels, type Label } from "./labelsApi";
import { labelDisplayName } from "./labelDisplay";

type Props = { open: boolean; onClose: () => void };

export function ManageLabelsSheet({ open, onClose }: Props) {
  const [labels, setLabels] = useState<Label[]>([]);
  const [slug, setSlug] = useState("");
  const [name, setName] = useState("");
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    if (!open) return;
    listLabels()
      .then(setLabels)
      .catch(() => undefined);
  }, [open]);

  if (!open) return null;

  async function add() {
    if (!slug.trim() || !name.trim() || busy) return;
    setBusy(true);
    try {
      const created = await createLabel({
        slug: slug.trim(),
        name: name.trim(),
      });
      setLabels((curr) => [...curr, created]);
      setSlug("");
      setName("");
    } finally {
      setBusy(false);
    }
  }

  async function remove(id: number) {
    await deleteLabel(id);
    setLabels((curr) => curr.filter((label) => label.id !== id));
  }

  return (
    <div className="fixed inset-0 z-30 flex items-end justify-center bg-black/30">
      <div className="w-full max-w-[480px] rounded-t-2xl bg-life-card p-4 text-life-ink">
        <div className="mb-3 flex items-center justify-between">
          <div className="text-[16px] font-semibold">Labels</div>
          <button
            type="button"
            onClick={onClose}
            className="text-life-ink-3"
          >
            Close
          </button>
        </div>
        <ul className="mb-4 divide-y divide-life-line">
          {labels.map((label) => (
            <li
              key={label.id}
              className="flex items-center justify-between py-2 text-[13.5px]"
            >
              <span>
                <span className="font-medium">{labelDisplayName(label)}</span>
                {label.slug !== "improve-life-assistant" && (
                  <span className="ml-2 text-life-ink-3">#{label.slug}</span>
                )}
              </span>
              <button
                type="button"
                onClick={() => void remove(label.id)}
                className="text-[12px] text-rose-600"
              >
                Delete
              </button>
            </li>
          ))}
        </ul>
        <div className="flex flex-col gap-2 border-t border-life-line pt-3">
          <input
            value={slug}
            onChange={(e) => setSlug(e.target.value)}
            placeholder="slug (lowercase-kebab)"
            className="rounded-xl border border-life-line bg-white px-3 py-2 text-[13px] outline-none"
          />
          <input
            value={name}
            onChange={(e) => setName(e.target.value)}
            placeholder="name"
            className="rounded-xl border border-life-line bg-white px-3 py-2 text-[13px] outline-none"
          />
          <button
            type="button"
            onClick={() => void add()}
            disabled={busy}
            className="rounded-xl bg-life-accent px-3 py-2 text-[13px] font-medium text-white disabled:opacity-50"
          >
            Add label
          </button>
        </div>
      </div>
    </div>
  );
}

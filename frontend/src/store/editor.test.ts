/** Логика конструктора: добавление, перемещение, скрытие блоков, undo/redo. */
import { beforeEach, describe, expect, it, vi } from "vitest";
import type { Site } from "../api/types";
import { defaultContentFor } from "../templates/catalog";

vi.mock("../api/endpoints", () => ({
  sitesApi: { update: vi.fn(async (_id: string, body: unknown) => ({ site: { ...site, ...(body as object) } })) },
}));

const site: Site = {
  id: "site-1",
  type: "links",
  title: "Мой сайт",
  content_json: defaultContentFor("links", "Мой сайт"),
  custom_code: null,
  domain: null,
  dns_item_address: null,
  collection_address: null,
  status: "draft",
  storage_bag_id: null,
  published_at: null,
  created_at: new Date().toISOString(),
  updated_at: new Date().toISOString(),
};

const { useEditorStore } = await import("./editor");

describe("editor store", () => {
  beforeEach(() => {
    useEditorStore.getState().reset();
    useEditorStore.getState().load(site);
  });

  it("загружает копию контента, не трогая исходный сайт", () => {
    const state = useEditorStore.getState();
    state.updateBlock(state.content!.blocks[0].id, { title: "Изменено" });
    expect(site.content_json.blocks[0].props.title).not.toBe("Изменено");
  });

  it("добавляет и удаляет блоки", () => {
    const before = useEditorStore.getState().content!.blocks.length;
    useEditorStore.getState().addBlock("gallery");
    expect(useEditorStore.getState().content!.blocks.length).toBe(before + 1);

    const added = useEditorStore.getState().content!.blocks.at(-1)!;
    expect(added.type).toBe("gallery");

    useEditorStore.getState().removeBlock(added.id);
    expect(useEditorStore.getState().content!.blocks.length).toBe(before);
  });

  it("перемещает блок и не выходит за границы списка", () => {
    const blocks = useEditorStore.getState().content!.blocks;
    const [first, second] = blocks;

    useEditorStore.getState().moveBlock(first.id, 1);
    expect(useEditorStore.getState().content!.blocks[0].id).toBe(second.id);

    useEditorStore.getState().moveBlock(second.id, -1); // уже первый — ничего не меняется
    expect(useEditorStore.getState().content!.blocks[0].id).toBe(second.id);
  });

  it("скрывает и показывает блок", () => {
    const blockId = useEditorStore.getState().content!.blocks[0].id;
    useEditorStore.getState().toggleBlock(blockId);
    expect(useEditorStore.getState().content!.blocks[0].hidden).toBe(true);
    useEditorStore.getState().toggleBlock(blockId);
    expect(useEditorStore.getState().content!.blocks[0].hidden).toBe(false);
  });

  it("отменяет и возвращает изменения", () => {
    const blockId = useEditorStore.getState().content!.blocks[0].id;
    useEditorStore.getState().updateBlock(blockId, { title: "Первая версия" });
    useEditorStore.getState().updateBlock(blockId, { title: "Вторая версия" });

    expect(useEditorStore.getState().canUndo()).toBe(true);
    useEditorStore.getState().undo();
    expect(useEditorStore.getState().content!.blocks[0].props.title).toBe("Первая версия");

    useEditorStore.getState().redo();
    expect(useEditorStore.getState().content!.blocks[0].props.title).toBe("Вторая версия");
  });

  it("помечает черновик как несохранённый и сохраняет по требованию", async () => {
    const blockId = useEditorStore.getState().content!.blocks[0].id;
    useEditorStore.getState().updateBlock(blockId, { title: "Автосохранение" });
    expect(useEditorStore.getState().saveState).toBe("dirty");

    await useEditorStore.getState().saveNow();
    expect(useEditorStore.getState().saveState).toBe("saved");
  });
});

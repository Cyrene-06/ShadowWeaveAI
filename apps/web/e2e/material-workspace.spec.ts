import { expect, test } from "@playwright/test";
import { readFile } from "node:fs/promises";
import path from "node:path";

const base = process.env.PHASE_TWO_WEB_URL;
const fixture = process.env.PHASE_TWO_SPOKEN_VIDEO;
const output = "../../artifacts/phase-two-browser";

test("real speech search seeks to source and exports reviewed evidence", async ({
  page,
}, info) => {
  test.skip(
    !base || !fixture,
    "Set PHASE_TWO_WEB_URL and PHASE_TWO_SPOKEN_VIDEO to run with the live API and Worker",
  );
  await page.setViewportSize({ width: 390, height: 844 });
  const errors: string[] = [];
  page.on("pageerror", (e) => errors.push(e.message));
  await page.goto(base!);
  await page.getByRole("button", { name: "创建账号", exact: true }).click();
  await page.getByLabel("邮箱").fill(`material-${Date.now()}@example.test`);
  await page
    .getByLabel("密码（至少 12 位）")
    .fill("phase-two-browser-password");
  await page.getByRole("button", { name: "注册并进入" }).click();
  await page.getByLabel("项目名称").fill("NASA · 素材证据回看");
  await page.getByRole("button", { name: "创建项目", exact: true }).click();
  const media = page.locator("#material-workspace");
  await media.getByLabel("视频文件").setInputFiles(path.resolve(fixture!));
  await media
    .getByLabel("素材来源与使用范围")
    .fill("NASA SVS 10451，开发核验用途");
  await media.getByLabel("确认有权在本项目内处理此素材").check();
  await media.getByRole("button", { name: "上传并分析" }).click();
  await expect(media.getByText(/分析完成 · 转写 \d+ 段/)).toBeVisible({
    timeout: 45_000,
  });
  await media.getByLabel("片段关键词").fill("notpresentxyzz");
  await media.getByRole("button", { name: "检索片段" }).click();
  await expect(media.getByText("无匹配片段", { exact: false })).toBeVisible();
  await media.getByLabel("片段关键词").fill("giant leap");
  await media.getByRole("button", { name: "检索片段" }).click();
  await media.getByRole("button", { name: "回看片段" }).first().click();
  const inspect = media.getByRole("article");
  await expect(inspect.getByText(/原片回看/)).toBeVisible();
  const video = inspect.locator("video");
  const videoState = () =>
    video.evaluate((node: HTMLVideoElement) => ({
      time: node.currentTime,
      ready: node.readyState,
    }));
  const heading = await inspect.getByRole("heading").textContent();
  const start = Number(heading?.match(/·\s*([\d.]+)–/)?.[1]);
  expect(start).toBeGreaterThan(0);
  await expect
    .poll(async () => {
      const actual = await videoState();
      return actual.ready >= 2 ? Math.abs(actual.time - start) : 100;
    })
    .toBeLessThan(0.15);
  await expect(
    inspect.getByRole("img", { name: "当前片段的代表帧" }),
  ).toBeVisible();
  await inspect.getByText("核对证据来源", { exact: true }).click();
  await expect(
    inspect.getByText("原片 SHA-256", { exact: true }),
  ).toBeVisible();
  await inspect.getByText("人工复核并导出证据", { exact: true }).click();
  await inspect.getByLabel("故事要求编号").fill("first-step");
  await inspect.getByLabel("语义支持").selectOption("supported");
  await inspect.getByLabel("画质与声音足以使用").check();
  await inspect.getByLabel("我已回看原片并核对该要求").check();
  const download = page.waitForEvent("download");
  await inspect.getByRole("button", { name: "下载证据清单" }).click();
  const manifestPath = info.outputPath("materials-manifest.json");
  await (await download).saveAs(manifestPath);
  const contents = JSON.parse(await readFile(manifestPath, "utf8"));
  expect(contents.evidence).toEqual([
    expect.objectContaining({
      in_ms: Math.round(start * 1000),
      requirement_keys: ["first-step"],
      semantic_support: "supported",
    }),
  ]);
  await expect
    .poll(() =>
      page.evaluate(
        () => document.documentElement.scrollWidth - window.innerWidth,
      ),
    )
    .toBeLessThanOrEqual(1);
  expect(errors).toEqual([]);
  await media.screenshot({
    path: `${output}/workspace-narrow.png`,
    animations: "disabled",
  });
});

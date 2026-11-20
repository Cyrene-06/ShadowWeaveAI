import { expect, test } from "@playwright/test";
import { readFile } from "node:fs/promises";
import path from "node:path";
import { pathToFileURL } from "node:url";

const fixture = process.env.PHASE_TWO_TIMING_PACKET;

test("matched proxy sessions record positions, not human verdicts", async ({
  page,
}, info) => {
  test.skip(
    !fixture,
    "Generate a real timing packet and set PHASE_TWO_TIMING_PACKET",
  );
  const observer = JSON.parse(
    await readFile(path.join(fixture!, "observer.json"), "utf8"),
  );
  await page.addInitScript(() => {
    const monotonicNow = performance.now.bind(performance);
    const mockClock = Performance.prototype as Performance & {
      timerOffset?: number;
    };
    Object.defineProperty(performance, "now", {
      value: () => monotonicNow() + (mockClock.timerOffset ?? 0),
    });
  });
  for (const [participant, arm, expected] of [
    ["P1", "A", 0],
    ["P2", "B", 16],
  ] as const) {
    await page.goto(
      pathToFileURL(path.resolve(fixture!, participant, "index.html")).href,
    );
    const start = page.getByRole("button", { name: "开始本题" });
    const locate = page.getByRole("button", {
      name: arm === "A" ? /^打开 clip-/ : /^跳转 clip-/,
    });
    const submit = page.getByRole("button", { name: "记录当前位置" });
    await expect(locate).toBeHidden();
    await start.click();
    await locate.first().click();
    await expect(submit).toBeEnabled();
    const time = await page
      .locator("video")
      .evaluate((video: HTMLVideoElement) => video.currentTime);
    expect(Math.abs(time - expected)).toBeLessThan(0.15);
    await submit.click();
    await page.getByRole("button", { name: "结束本题" }).click();
    for (let i = 0; i < 3; i++) {
      await start.click();
      if (i === 0) {
        await page.evaluate(() => {
          (
            Performance.prototype as Performance & { timerOffset?: number }
          ).timerOffset = 60_001;
        });
        await expect(
          page.getByText("本题超时，已保留提交记录。"),
        ).toBeVisible();
      } else {
        await page.getByRole("button", { name: "弃答（未找到）" }).click();
      }
    }
    const download = page.waitForEvent("download");
    await page.getByRole("button", { name: "下载本场记录" }).click();
    const saved = info.outputPath(`${participant}-timing.json`);
    await (await download).saveAs(saved);
    const record = JSON.parse(await readFile(saved, "utf8"));
    expect(record.participant).toBe(participant);
    expect(record.replay_sha256).toBe(observer.replay_sha256);
    expect(record.study_commitment).toBe(observer.study_commitment);
    expect(record.trials).toHaveLength(4);
    expect(record.trials[0]).toMatchObject({
      arm,
      outcome: "submitted",
      playback_errors: 0,
    });
    expect(record.trials[0]).not.toHaveProperty("correct");
    expect(record.trials[0].submissions).toHaveLength(1);
    expect(
      Math.abs(record.trials[0].submissions[0].point_ms - expected * 1000),
    ).toBeLessThan(150);
    expect(record.trials[0].submissions[0].elapsed_ms).toBeLessThan(60_000);
    expect(record.trials[1]).toMatchObject({
      outcome: "timeout",
      elapsed_ms: 60_000,
      submissions: [],
    });
    expect(
      record.trials.find((row: { trial_id: string }) => row.trial_id === "T4"),
    ).toMatchObject({
      outcome: "abstained",
      submissions: [],
    });
  }
});

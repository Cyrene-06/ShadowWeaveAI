import { expect, test, type Page } from "@playwright/test";
import path from "node:path";

const output = "../../artifacts/phase-one/browser/web-ui";

async function expectNoHorizontalOverflow(page: Page) {
  await expect
    .poll(() =>
      page.evaluate(
        () => document.documentElement.scrollWidth - window.innerWidth,
      ),
    )
    .toBeLessThanOrEqual(1);
}

for (const viewport of [
  { name: "desktop", width: 1440, height: 1000 },
  { name: "narrow", width: 390, height: 844 },
]) {
  test(`Web workbench shows rule results without page overflow (${viewport.name})`, async ({
    page,
  }) => {
    const errors: string[] = [];
    page.on("pageerror", (error) => errors.push(error.message));
    await page.setViewportSize({
      width: viewport.width,
      height: viewport.height,
    });
    await page.goto(process.env.WORKSPACE_WEB_URL || "http://127.0.0.1:5173");
    await expect(
      page.getByRole("heading", { name: "进入项目工作台" }),
    ).toBeVisible();
    await expectNoHorizontalOverflow(page);
    await page.screenshot({
      path: `${output}/login-${viewport.name}.png`,
      fullPage: true,
    });
    await page.keyboard.press("Tab");
    await expect(
      page.getByRole("link", { name: "跳到主要内容" }),
    ).toBeFocused();

    await page.getByRole("button", { name: "创建账号", exact: true }).click();
    await page
      .getByLabel("邮箱")
      .fill(`ui-${viewport.name}-${Date.now()}@example.test`);
    await page
      .getByLabel("密码（至少 12 位）")
      .fill("phase-one-browser-password");
    await page.getByRole("button", { name: "注册并进入" }).click();
    await expect(
      page.getByRole("heading", { name: "尚未选择项目" }),
    ).toBeVisible();
    await page.getByLabel("项目名称").fill("校园活动 · 剪辑复核");
    await page.getByRole("button", { name: "创建项目", exact: true }).click();
    await expect(
      page.getByRole("heading", { name: "校园活动 · 剪辑复核" }),
    ).toBeVisible();
    await page.getByRole("button", { name: "运行固定样例" }).click();
    await expect(page.getByText("样例检查通过", { exact: true })).toBeVisible();
    await expect(
      page.getByText("上传事件后：submitted", { exact: true }),
    ).toBeVisible();
    await expect(
      page.getByText("新证据验证后：fulfilled", { exact: true }),
    ).toBeVisible();
    await expect(page.getByText("证据不确定时，不能完成补拍")).toBeVisible();
    await expect(page.getByText("告别镜头：素材语义未确认。")).toBeVisible();
    await expect(page.getByText("高风险", { exact: true })).toBeVisible();
    await expectNoHorizontalOverflow(page);
    await page.screenshot({ path: `${output}/workspace-${viewport.name}.png` });

    const openingCard = page
      .getByRole("article")
      .filter({ has: page.getByRole("heading", { name: "开场环境" }) });
    await openingCard.getByText("逐需求证据", { exact: false }).click();
    await expect(
      openingCard.getByText("候选 2 · 合格 2 · 选中 1"),
    ).toBeVisible();
    await expect(
      openingCard.getByText("已选中 · 语义支持 · 质量达标"),
    ).toBeVisible();
    await page.getByRole("link", { name: "局部修改" }).click();
    await page.getByText("依赖传播路径", { exact: false }).click();
    await expect(
      page.locator(".path-list").getByText("开场字幕", { exact: true }),
    ).toBeVisible();
    await expectNoHorizontalOverflow(page);
    await page
      .locator("#editing")
      .screenshot({ path: `${output}/editing-${viewport.name}.png` });

    if (viewport.name === "desktop") {
      await page
        .getByLabel("选择媒体")
        .setInputFiles(
          path.resolve("../../artifacts/phase-one/media/generated-source.mp4"),
        );
      await expect(
        page.locator("pre").filter({ hasText: "real_media_probe" }),
      ).toBeVisible();
    }
    expect(errors).toEqual([]);
  });
}

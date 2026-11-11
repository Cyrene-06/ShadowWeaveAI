import { test, expect } from "@playwright/test";
import path from "node:path";

test("Web and Flutter read the same real API project and replay the rules", async ({
  page,
  context,
}) => {
  const errors: string[] = [];
  page.on("pageerror", (error) => errors.push(error.message));
  const stamp = Date.now();
  const email = `browser-${stamp}@example.test`,
    password = "phase-one-browser-password",
    name = `双端联调 ${stamp}`;
  await page.goto("http://127.0.0.1:5173");
  await page.getByRole("button", { name: "创建账号", exact: true }).click();
  await page.getByLabel("邮箱").fill(email);
  await page.getByLabel("密码（至少 12 位）").fill(password);
  await page.getByRole("button", { name: "注册并进入", exact: true }).click();
  await page.getByLabel("项目名称").fill(name);
  await page.getByRole("button", { name: "创建项目", exact: true }).click();
  await expect(
    page.getByRole("button", { name: new RegExp(name) }),
  ).toBeVisible();
  await page.getByRole("button", { name: "运行固定样例", exact: true }).click();
  await expect(page.getByText("样例检查通过", { exact: true })).toBeVisible();
  await expect(
    page.getByText("上传事件后：submitted", { exact: true }),
  ).toBeVisible();
  await expect(
    page.getByText("新证据验证后：fulfilled", { exact: true }),
  ).toBeVisible();
  await page
    .locator("input[type=file]")
    .setInputFiles(
      path.resolve("../../artifacts/phase-one/media/generated-source.mp4"),
    );
  await expect(
    page.locator("pre").filter({ hasText: "real_media_probe" }),
  ).toBeVisible();
  await page.screenshot({
    path: "../../artifacts/phase-one/browser/web.png",
    fullPage: true,
  });
  expect(errors).toEqual([]);

  const mobile = await context.newPage();
  mobile.on("pageerror", (error) => errors.push(error.message));
  await mobile.goto("http://127.0.0.1:8080");
  const enable = mobile.locator("flt-semantics-placeholder");
  await enable.waitFor({ state: "attached" });
  await enable.evaluate((e: HTMLElement) => e.click());
  await mobile.getByRole("textbox", { name: "邮箱" }).click();
  await mobile.keyboard.insertText(email);
  await mobile.getByRole("textbox", { name: "密码（至少 12 位）" }).click();
  await mobile.keyboard.insertText(password);
  await mobile.getByRole("button", { name: "登录", exact: true }).click();
  await expect(
    mobile.getByRole("button", { name: new RegExp(name) }),
  ).toBeVisible();
  await mobile.getByRole("button", { name: new RegExp(name) }).click();
  await mobile
    .getByRole("button", { name: "运行固定样例", exact: true })
    .click();
  await expect(mobile.getByText(/上传后：submitted/)).toBeVisible();
  await expect(mobile.getByText(/新证据验证后：fulfilled/)).toBeVisible();
  await mobile.screenshot({
    path: "../../artifacts/phase-one/browser/flutter.png",
    fullPage: true,
  });
  expect(errors).toEqual([]);
});

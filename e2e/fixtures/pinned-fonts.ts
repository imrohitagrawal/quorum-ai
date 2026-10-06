import { Page } from "@playwright/test";
import * as fs from "fs";
import * as path from "path";

/**
 * W41 (ADR-0149, CHG-031). The screenshot specs answer the page's Google Fonts
 * stylesheet request with a saved copy of Google's usual answer.
 *
 * Google sometimes answers the same request with a different build of the
 * Geist font (font addresses of the form `fonts.gstatic.com/l/font?kit=…`
 * instead of `fonts.gstatic.com/s/…`). Its letter widths at weights 550 to
 * 650 differ by about one font unit, which moved the trust-score card's bold
 * sentence and failed the screenshot compare at random (644, 589 and 234 px,
 * reproduced exactly by replaying that build on CI). The saved copy names only the usual `/s/`
 * files, so every screenshot gets the same fonts. The font files still come
 * from Google.
 *
 * A stylesheet request for any other address is aborted: the page then draws
 * in a fallback font and every screenshot fails, so a changed font link in
 * `workspace.html` cannot pass unnoticed. `google-fonts.json` records the
 * address, when and how the copy was taken, and its SHA-1.
 */
const RECORD = JSON.parse(fs.readFileSync(path.join(__dirname, "google-fonts.json"), "utf8")) as {
  url: string;
};
const STYLESHEET = fs.readFileSync(path.join(__dirname, "google-fonts.css"));

/**
 * Returns `served()`: how many stylesheet requests this route answered from
 * the saved copy. Google's usual answer is byte-identical to that copy, so a
 * pin that silently stopped matching would leave every screenshot green; the
 * specs assert `served() > 0` to catch that.
 */
export async function pinGoogleFonts(page: Page): Promise<{ served: () => number }> {
  let served = 0;
  await page.route("https://fonts.googleapis.com/**", async (route) => {
    if (route.request().url() !== RECORD.url) return route.abort();
    await route.fulfill({ status: 200, contentType: "text/css; charset=utf-8", body: STYLESHEET });
    served += 1;
  });
  return { served: () => served };
}

import express from "express";
import multer from "multer";
import { LiteParse } from "@llamaindex/liteparse";

const app = express();
const upload = multer();

const parser = new LiteParse({
  ocrEnabled: true,
  ocrLanguage: "spa+eng",
  preciseBoundingBox: true,
});

app.get("/health", (_req, res) => {
  res.json({ status: "ok", parser: "liteparse" });
});

app.post("/parse", upload.single("file"), async (req, res) => {
  try {
    if (!req.file) {
      res.status(400).json({ status: "error", message: "file is required" });
      return;
    }
    const result = await parser.parse(req.file.buffer);
    res.json({
      status: "ok",
      text: result.text || "",
      pages: result.pages || [],
      metadata: {
        filename: req.file.originalname,
        mimetype: req.file.mimetype,
        parser: "liteparse",
        pages: result.pages?.length || 0,
      },
    });
  } catch (err) {
    res.status(500).json({
      status: "error",
      message: String(err?.message || err),
    });
  }
});

const port = process.env.PORT || 8787;
app.listen(port, () => {
  console.log(`LiteParse service on http://127.0.0.1:${port}`);
});


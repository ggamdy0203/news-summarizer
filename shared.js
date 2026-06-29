// index.html / digest.html 공용 로직 (Gemini 호출, API 키 저장, 요약 렌더링)

const STORAGE_KEY_API = "news_summarizer_api_key";
const STORAGE_KEY_HISTORY = "news_summarizer_history";
const MODEL = "gemini-2.5-flash";

const SUMMARY_FORMAT_INSTRUCTION =
  `요약은 3~4개의 핵심 포인트로 나눠서, 포인트마다 줄을 바꾸고 맨 앞에 "• "를 붙여줘. ` +
  `각 포인트는 한 문장으로 짧고 명확하게 써줘.`;

function loadApiKey() {
  return localStorage.getItem(STORAGE_KEY_API) || "";
}

function saveApiKey(key) {
  localStorage.setItem(STORAGE_KEY_API, key);
}

function escapeHtml(text) {
  const div = document.createElement("div");
  div.textContent = text;
  return div.innerHTML;
}

async function callGemini(apiKey, contents, tools) {
  const endpoint = `https://generativelanguage.googleapis.com/v1beta/models/${MODEL}:generateContent?key=${encodeURIComponent(apiKey)}`;
  const body = { contents };
  if (tools) body.tools = tools;

  const response = await fetch(endpoint, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });

  const data = await response.json();
  if (!response.ok) {
    const message = data.error && data.error.message ? data.error.message : `HTTP ${response.status}`;
    throw new Error(message);
  }
  return data;
}

function extractCandidateText(data) {
  const candidate = data.candidates && data.candidates[0];
  if (!candidate) return { text: "", status: null };
  const parts = (candidate.content && candidate.content.parts) || [];
  const text = parts.map(p => p.text || "").join("").trim();
  const urlMeta = candidate.urlContextMetadata && candidate.urlContextMetadata.urlMetadata;
  const status = urlMeta && urlMeta[0] && urlMeta[0].urlRetrievalStatus;
  return { text, status };
}

async function fetchArticleTextViaReader(url) {
  // 네이버 뉴스처럼 Gemini가 직접 못 읽는 사이트를 위한 우회 경로.
  // r.jina.ai는 임의 URL을 읽어서 정리된 텍스트로 반환해주는 무료 리더 서비스.
  const readerUrl = `https://r.jina.ai/${url}`;
  const response = await fetch(readerUrl);
  if (!response.ok) {
    throw new Error(`본문을 가져오지 못했습니다 (HTTP ${response.status}).`);
  }
  const text = await response.text();
  if (!text || text.trim().length < 50) {
    throw new Error("본문 내용이 너무 적어 요약할 수 없습니다.");
  }
  return text.slice(0, 16000);
}

async function summarizeUrl(url, apiKey) {
  const directPrompt = `다음 링크에 접속해서 글 내용을 읽고 핵심만 한국어로 요약해줘. ` +
    `${SUMMARY_FORMAT_INSTRUCTION} ` +
    `머릿말이나 따옴표 없이 바로 첫 포인트부터 시작해.\n\n링크: ${url}`;

  const directData = await callGemini(
    apiKey,
    [{ parts: [{ text: directPrompt }] }],
    [{ url_context: {} }]
  );
  const { text, status } = extractCandidateText(directData);

  if (status === "URL_RETRIEVAL_STATUS_SUCCESS" && text) {
    return text;
  }

  // Gemini가 직접 못 읽는 사이트(예: 네이버 뉴스)는 리더 서비스로 본문을 가져와 텍스트로 요약 요청
  const articleText = await fetchArticleTextViaReader(url);
  const fallbackPrompt = `다음은 어떤 기사 페이지에서 가져온 텍스트다. 광고/메뉴/구독 안내 같은 ` +
    `본문과 무관한 내용은 무시하고, 핵심만 한국어로 요약해줘. ${SUMMARY_FORMAT_INSTRUCTION} ` +
    `머릿말이나 따옴표 없이 바로 요약문부터 시작해.\n\n${articleText}`;
  const fallbackData = await callGemini(apiKey, [{ parts: [{ text: fallbackPrompt }] }]);
  const fallbackResult = extractCandidateText(fallbackData);

  return fallbackResult.text || "요약 내용을 생성하지 못했습니다.";
}

function loadHistory() {
  try {
    return JSON.parse(localStorage.getItem(STORAGE_KEY_HISTORY) || "[]");
  } catch (e) {
    return [];
  }
}

function saveHistory(history) {
  localStorage.setItem(STORAGE_KEY_HISTORY, JSON.stringify(history));
}

function addToHistory(url, summary, title, category) {
  const history = loadHistory();
  if (history.some(h => h.url === url)) {
    return false; // 이미 저장된 기사
  }
  history.unshift({
    id: `${Date.now()}-${Math.random().toString(36).slice(2, 8)}`,
    url,
    title: title || "",
    summary,
    category: category || "기타",
    createdAt: new Date().toISOString(),
  });
  saveHistory(history);
  return true;
}

function renderSummaryHtml(summary) {
  const lines = summary.split("\n").map(l => l.trim()).filter(Boolean);
  const points = lines.map(l => l.replace(/^[•\-\*]\s*/, ""));
  if (points.length <= 1) {
    return `<p>${escapeHtml(summary)}</p>`;
  }
  return `<ul class="summaryList">${points.map(p => `<li>${escapeHtml(p)}</li>`).join("")}</ul>`;
}

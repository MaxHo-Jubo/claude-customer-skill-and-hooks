/**
 * jest moduleNameMapper 用的 css/scss/less 樣式檔 stub。
 * 被對跑的 reducer/action creator/util 若間接 import 到樣式檔，這裡回傳空物件，
 * 避免 jest 嘗試解析非 JS 語法而整個 require chain 炸掉——差異測試只在意邏輯輸出，
 * 不在意樣式的實際內容。
 */
module.exports = {};

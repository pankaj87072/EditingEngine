const KEY = 'avg.token.v1';
export const UNAUTHORIZED_EVENT = 'avg:unauthorized';

export const getToken = (): string | null => {
  try {
    return localStorage.getItem(KEY);
  } catch {
    return null;
  }
};
export const setToken = (t: string | null) => {
  try {
    if (t) localStorage.setItem(KEY, t);
    else localStorage.removeItem(KEY);
  } catch {
    /* storage blocked */
  }
};
/** <video src> and download links can't send headers, so they carry the token in the URL. */
export const withToken = (url: string) => {
  const t = getToken();
  return t ? `${url}${url.includes('?') ? '&' : '?'}token=${encodeURIComponent(t)}` : url;
};

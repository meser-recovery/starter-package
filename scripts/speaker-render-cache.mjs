const MEASUREMENT_FIELDS = Object.freeze([
  "measured_I", "measured_TP", "measured_LRA", "measured_thresh", "offset"
]);

function copyMeasurements(value) {
  if (!value || typeof value !== "object") throw new Error("Измерения громкости недопустимы.");
  const result = {};
  for (const field of MEASUREMENT_FIELDS) {
    const number = Number(value[field]);
    if (!Number.isFinite(number) || number < -120 || number > 120) {
      throw new Error("Измерения громкости недопустимы.");
    }
    result[field] = number;
  }
  return result;
}

export class LoudnessMeasurementCache {
  constructor(limit = 128) {
    if (!Number.isInteger(limit) || limit < 1) throw new Error("Размер кэша должен быть положительным целым числом.");
    this.limit = limit;
    this.entries = new Map();
  }

  get size() { return this.entries.size; }

  get(key) {
    if (typeof key !== "string" || !this.entries.has(key)) return null;
    const value = this.entries.get(key);
    this.entries.delete(key);
    this.entries.set(key, value);
    return copyMeasurements(value);
  }

  set(key, measurements) {
    if (typeof key !== "string" || !key) throw new Error("Ключ измерения громкости недопустим.");
    const value = Object.freeze(copyMeasurements(measurements));
    this.entries.delete(key);
    this.entries.set(key, value);
    while (this.entries.size > this.limit) this.entries.delete(this.entries.keys().next().value);
    return copyMeasurements(value);
  }

  clear() { this.entries.clear(); }
}

export class SourceIdentityRegistry {
  constructor() { this.reset(); }

  identity(source) {
    if (!(source instanceof Blob)) throw new Error("Источник аудио недоступен.");
    let identity = this.identities.get(source);
    if (!identity) {
      identity = `source-${++this.sequence}`;
      this.identities.set(source, identity);
    }
    return identity;
  }

  reset() {
    this.identities = new WeakMap();
    this.sequence = 0;
  }
}

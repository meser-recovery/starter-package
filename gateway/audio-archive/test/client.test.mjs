import test from "node:test";
import assert from "node:assert/strict";
import { createHash } from "node:crypto";
import {
  DEFAULT_AUDIO_PART_BYTES, MAX_AUDIO_PART_BYTES, MAX_AUDIO_SESSION_BYTES, Sha256, assetName,
  createIngestionPlan, isUuid, reconstructSessionTracks, serializeIngestionPlan, sha256Hex, validateSessionManifest
} from "../../../scripts/audio-archive-client.mjs";

function nodeSha(bytes) { return createHash("sha256").update(bytes).digest("hex"); }

test("incremental SHA-256 matches known vectors and block boundaries", async () => {
  assert.equal(new Sha256().update(new Uint8Array()).digestHex(), "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855");
  assert.equal(new Sha256().update(new TextEncoder().encode("abc")).digestHex(), "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad");
  for (const length of [55, 56, 63, 64, 65, 127, 128, 129]) {
    const bytes = Uint8Array.from({ length }, (_, index) => index & 255);
    const incremental = new Sha256();
    for (let offset = 0; offset < bytes.length; offset += 7) incremental.update(bytes.subarray(offset, offset + 7));
    assert.equal(incremental.digestHex(), nodeSha(bytes), `boundary ${length}`);
    assert.equal(await sha256Hex(bytes), nodeSha(bytes));
  }
});

test("chunk planner uses 16 MiB default, permits 64 MiB boundary, and rejects unsafe inputs", async () => {
  const bytes = new Uint8Array(DEFAULT_AUDIO_PART_BYTES + 1);
  bytes[bytes.length - 1] = 7;
  const plan = await createIngestionPlan([new File([bytes], "meeting.wav", { type: "audio/wav" })]);
  assert.deepEqual(plan.tracks[0].parts.map((part) => part.sizeBytes), [DEFAULT_AUDIO_PART_BYTES, 1]);
  assert.equal(plan.tracks[0].sha256, nodeSha(bytes));
  const boundary = await createIngestionPlan([new File([Uint8Array.of(1)], "a.mp3", { type: "audio/mpeg" })], MAX_AUDIO_PART_BYTES);
  assert.equal(boundary.tracks[0].parts.length, 1);
  await assert.rejects(() => createIngestionPlan([new File([Uint8Array.of(1)], "a.mp3")], MAX_AUDIO_PART_BYTES + 1), /размер части/);
  await assert.rejects(() => createIngestionPlan([new File([], "empty.wav", { type: "audio/wav" })]), /Пустые/);
  const oversized = { name: "large.wav", type: "audio/wav", size: MAX_AUDIO_SESSION_BYTES + 1, slice() { throw new Error("must not read"); } };
  await assert.rejects(() => createIngestionPlan([oversized]), /500 МБ/);
  assert.equal(isUuid("not-a-uuid"), false);
  assert.throws(() => assetName("not-a-uuid", 1), /идентификатор/);
});

test("chunk planner keeps identifiers and hashes stable for one idempotency operation", async () => {
  const files = [new File([Uint8Array.of(1, 2, 3, 4, 5)], "meeting.wav", { type: "audio/wav" })];
  const options = { idempotencyKey: "stable-operation-key" };
  const first = await createIngestionPlan(files, 2, options);
  const second = await createIngestionPlan(files, 2, options);
  assert.deepEqual(serializeIngestionPlan(second), serializeIngestionPlan(first));
  assert.equal(isUuid(first.tracks[0].trackId), true);
  assert.equal(isUuid(first.tracks[0].blobId), true);
});

test("chunk planner observes cancellation immediately after every part read", async () => {
  const controller = new AbortController();
  let reads = 0;
  const file = {
    name: "meeting.wav", type: "audio/wav", size: 1,
    slice() {
      return { async arrayBuffer() { reads++; controller.abort(); return Uint8Array.of(7).buffer; } };
    }
  };
  await assert.rejects(
    () => createIngestionPlan([file], 1, { idempotencyKey: "cancel-operation-key", signal: controller.signal }),
    (error) => error?.name === "AbortError"
  );
  assert.equal(reads, 1);
});

test("ordered parts reconstruct byte-identically and corruption fails closed", async () => {
  const sessionId = "11111111-1111-4111-8111-111111111111";
  const trackId = "22222222-2222-4222-8222-222222222222";
  const blobId = "33333333-3333-4333-8333-333333333333";
  const chunks = [Uint8Array.from([1, 2, 3]), Uint8Array.from([4, 5])];
  const complete = Buffer.concat(chunks.map((chunk) => Buffer.from(chunk)));
  const parts = chunks.map((chunk, index) => {
    const name = assetName(blobId, index + 1);
    return { partNumber: index + 1, sizeBytes: chunk.length, sha256: nodeSha(chunk), assetName: name, assetId: index + 10,
      downloadUrl: `https://github.com/meser-recovery/audio-archive/releases/download/audio-session-${sessionId}/${name}` };
  });
  const workflow = (name) => ({ workflow: name, status: "new", currentDraft: null, outputs: [], deletedVersions: [], nextVersion: 1 });
  const session = {
    schemaVersion: 1, revision: 1, id: sessionId, title: "Запись", recordedAt: null,
    createdAt: "2026-01-01T00:00:00.000Z", updatedAt: "2026-01-01T00:00:00.000Z",
    origin: { kind: "manual", externalId: null }, storage: { releaseId: 1, tag: `audio-session-${sessionId}` },
    lifecycle: { state: "incoming" }, sourceState: "available",
    sourceTracks: [{ trackId, blobId, ordinal: 1, originalName: "meeting.wav", mediaType: "audio/wav", sizeBytes: complete.length, sha256: nodeSha(complete), parts }],
    deletedSources: null, workflows: { announcement: workflow("announcement"), speaker: workflow("speaker") },
    relations: { supersedesSessionId: null, supersededBySessionId: null }, transaction: { state: "finalized", id: sessionId }
  };
  assert.equal(validateSessionManifest(session), true);
  assert.equal(validateSessionManifest({ ...session, unexpected: true }), false);
  const goodFetch = async (url) => new Response(chunks[parts.findIndex((part) => part.downloadUrl === url)]);
  const [file] = await reconstructSessionTracks(session, goodFetch);
  assert.deepEqual(new Uint8Array(await file.arrayBuffer()), new Uint8Array(complete));
  await assert.rejects(() => reconstructSessionTracks(session, async () => new Response(Uint8Array.of(9, 9, 9))), /целостности/);
  assert.equal(validateSessionManifest({ ...session, id: "malformed" }), false);
});

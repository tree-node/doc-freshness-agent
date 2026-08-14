/**
 * fixture の読み込み口。本物のAPIができるまでの唯一の「データが実際に置いてある場所」。
 *
 * ここ以外のファイル（derive.js / client.js / コンポーネント）は、この配列が
 * PipelineResult の配列であることだけを知っていればよい。fixture を追加・削除する
 * ときはこのファイルだけを触ればよい。
 */
import ikukai from '../mock/result-ikukai.json';
import rodo138 from '../mock/result-rodo138.json';

/** @type {import('./types.js').PipelineResult[]} */
export const PIPELINE_RESULTS = [ikukai, rodo138];

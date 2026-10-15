/**
 * The three wall modes as React shells around their engines (spotlight, gallery) or
 * plain markup (categories).
 */
import { useEffect, useRef, useState, type CSSProperties } from 'react';
import type { GallerySpeed, WallCategory, WallCategoryVerdict, WallPhoto } from '../api/types';
import { compactColumns, verdictAlign, verdictIndex, type VerdictAlign } from './categories';
import { GalleryEngine } from './galleryEngine';
import { aspectOf } from './slide';
import { SpotlightEngine, type SpotlightInput } from './spotlightEngine';

export function Spotlight({ input }: { input: SpotlightInput }) {
  const stageRef = useRef<HTMLDivElement>(null);
  const engineRef = useRef<SpotlightEngine | null>(null);
  const inputRef = useRef(input);
  useEffect(() => {
    inputRef.current = input;
    engineRef.current?.update(input);
  }, [input]);
  useEffect(() => {
    const stage = stageRef.current;
    if (!stage) return undefined;
    const engine = new SpotlightEngine(stage, inputRef.current);
    engineRef.current = engine;
    engine.start();
    return () => {
      engine.stop();
      engineRef.current = null;
    };
  }, []);
  return <div ref={stageRef} className="wall-stage" data-testid="wall-spotlight" />;
}

export function Gallery({
  photos,
  rows,
  speed,
}: {
  photos: readonly WallPhoto[];
  rows: number;
  speed: GallerySpeed;
}) {
  const stageRef = useRef<HTMLDivElement>(null);
  const engineRef = useRef<GalleryEngine | null>(null);
  const inputRef = useRef({ photos, rows, speed });
  useEffect(() => {
    inputRef.current = { photos, rows, speed };
    engineRef.current?.update({ photos, rows, speed });
  }, [photos, rows, speed]);
  useEffect(() => {
    const stage = stageRef.current;
    if (!stage) return undefined;
    const engine = new GalleryEngine(stage, inputRef.current);
    engineRef.current = engine;
    engine.start();
    return () => {
      engine.stop();
      engineRef.current = null;
    };
  }, []);
  return <div ref={stageRef} className="wall-gallery" data-testid="wall-gallery" />;
}

function Verdict({ verdict, align }: { verdict: WallCategoryVerdict; align?: VerdictAlign }) {
  return (
    <p className="wall-cat-verdict" data-testid="wall-verdict" data-align={align}>
      {verdict.emoji ? (
        <span className="wall-cat-verdict-emoji" aria-hidden="true">
          {verdict.emoji}
        </span>
      ) : null}
      {verdict.text}
    </p>
  );
}

function WinnerPhoto({
  winner,
  index,
  compact,
  verdict,
  align,
}: {
  winner: WallCategory['winners'][number];
  index: number;
  /** more than 3 winners: uniform cells, the place number on the photo */
  compact: boolean;
  /** this photo is the one the AI's verdict is about */
  verdict: WallCategoryVerdict | null;
  /** where the verdict sits under the photo: it may be wider than the photo */
  align: VerdictAlign;
}) {
  const [loaded, setLoaded] = useState(false);
  const { photo } = winner;
  const aspect = String(aspectOf(photo));
  return (
    <figure className="wall-cat-photo" data-index={index} data-verdict={verdict ? '' : undefined}>
      <div
        className="wall-cat-pic"
        // --a: the aspect for wall.css, which fits the pictures into the row's width
        style={compact ? undefined : ({ aspectRatio: aspect, '--a': aspect } as CSSProperties)}
      >
        <img
          src={photo.urls.m}
          alt={`Foto von ${photo.author}`}
          decoding="async"
          draggable={false}
          data-loaded={loaded ? '' : undefined}
          onLoad={() => setLoaded(true)}
        />
        {compact ? (
          <span className="wall-cat-rank" aria-hidden="true">
            {index + 1}
          </span>
        ) : null}
      </div>
      <span className="wall-cat-value">{winner.label}</span>
      <figcaption className="wall-cat-by">von {photo.author}</figcaption>
      {verdict && !compact ? <Verdict verdict={verdict} align={align} /> : null}
    </figure>
  );
}

function CategoryCard({ category }: { category: WallCategory }) {
  const count = category.winners.length;
  const compact = count > 3;
  const verdict = category.verdict;
  const verdictAt = verdict ? verdictIndex(category) : -1;
  return (
    <div className="wall-cat" data-testid="wall-category" data-category={category.id}>
      <div className="wall-cat-head">
        <span className="wall-cat-emoji" aria-hidden="true">
          {category.emoji}
        </span>
        <h2 className="wall-cat-title">{category.title}</h2>
        <p className="wall-cat-line">{category.line}</p>
      </div>
      <div className="wall-cat-side" data-verdict={verdict ? '' : undefined}>
        <div
          className="wall-cat-winners"
          data-count={count}
          data-compact={compact ? '' : undefined}
          data-verdict={verdict && !compact ? '' : undefined}
          data-cols={compact ? compactColumns(count) : undefined}
        >
          {category.winners.map((w, i) => (
            <WinnerPhoto
              key={w.photo.id}
              winner={w}
              index={i}
              compact={compact}
              verdict={i === verdictAt ? verdict : null}
              align={verdictAlign(i, count)}
            />
          ))}
        </div>
        {/* the compact grid has no room under a cell: the verdict goes under the grid,
            its photo is ringed */}
        {verdict && compact ? <Verdict verdict={verdict} /> : null}
      </div>
    </div>
  );
}

export function Categories({
  categories,
  perCategoryS,
}: {
  categories: readonly WallCategory[];
  perCategoryS: number;
}) {
  const [turn, setTurn] = useState(0);
  useEffect(() => {
    const timer = setInterval(() => setTurn((t) => t + 1), Math.max(4, perCategoryS) * 1000);
    return () => clearInterval(timer);
  }, [perCategoryS]);
  const category = categories.length > 0 ? categories[turn % categories.length] : undefined;
  if (!category) return null;
  return (
    <div className="wall-cats">
      <CategoryCard key={`${category.id}:${turn}`} category={category} />
    </div>
  );
}

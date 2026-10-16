/**
 * The three wall modes as React shells around their engines (spotlight, gallery) or
 * plain markup (categories).
 */
import { useEffect, useRef, useState, type CSSProperties } from 'react';
import type { CategoryWinner, GallerySpeed, WallCategory, WallPhoto } from '../api/types';
import { captionOf, compactColumns, coverBox, verdictAlign, type VerdictAlign } from './categories';
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

/** The compact grid's cells are 3:4 (wall.css). */
const COMPACT_ASPECT = 3 / 4;

type Comment = NonNullable<CategoryWinner['comment']>;

/** The AI's comment: a bubble with its emoji; „KI“ is the marker (wall.css ::before). */
function Verdict({ comment, align, place }: { comment: Comment; align?: VerdictAlign; place?: number }) {
  return (
    <p className="wall-cat-verdict" data-testid="wall-verdict" data-align={align} data-place={place}>
      {place ? (
        <span className="wall-cat-verdict-place" aria-hidden="true">
          {place}
        </span>
      ) : null}
      {comment.emoji ? (
        <span className="wall-cat-verdict-emoji" aria-hidden="true">
          {comment.emoji}
        </span>
      ) : null}
      {comment.text}
    </p>
  );
}

/** The frame around the focus object, with its name on a tag. */
function ObjectFrame({ winner, compact }: { winner: CategoryWinner; compact: boolean }) {
  const object = winner.object;
  if (!object) return null;
  const aspect = aspectOf(winner.photo);
  const rect = coverBox(object.box, aspect, compact ? COMPACT_ASPECT : aspect);
  if (!rect) return null;
  return (
    <div
      className="wall-cat-box"
      data-testid="wall-object-box"
      style={{
        left: `${rect.left}%`,
        top: `${rect.top}%`,
        width: `${rect.width}%`,
        height: `${rect.height}%`,
      }}
    >
      <span className="wall-cat-box-tag">{object.label_de}</span>
    </div>
  );
}

function WinnerPhoto({
  winner,
  index,
  count,
  compact,
  align,
  manyComments,
}: {
  winner: CategoryWinner;
  index: number;
  count: number;
  /** more than 3 winners: uniform cells, the place number on the photo */
  compact: boolean;
  /** where the comment sits under the photo: it may be wider than the photo */
  align: VerdictAlign;
  /** more than one photo in the row has a comment: each stays as wide as its photo */
  manyComments: boolean;
}) {
  const [loaded, setLoaded] = useState(false);
  const { photo, comment } = winner;
  const aspect = String(aspectOf(photo));
  const { headline, detail } = captionOf(winner);
  return (
    <figure
      className="wall-cat-photo"
      data-index={index}
      data-verdict={comment ? '' : undefined}
      data-many={manyComments ? '' : undefined}
    >
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
        <ObjectFrame winner={winner} compact={compact} />
        {compact ? (
          <span className="wall-cat-rank" aria-hidden="true">
            {index + 1}
          </span>
        ) : null}
      </div>
      <div className="wall-cat-cap" data-testid="wall-caption">
        {!compact && count > 1 ? (
          <span className="wall-cat-place" aria-label={`Platz ${index + 1}`}>
            {index + 1}
          </span>
        ) : null}
        <span className="wall-cat-headline">{headline}</span>
        {detail ? <span className="wall-cat-value">{detail}</span> : null}
      </div>
      <figcaption className="wall-cat-by">von {photo.author}</figcaption>
      {comment && !compact ? <Verdict comment={comment} align={manyComments ? 'center' : align} /> : null}
    </figure>
  );
}

/** Comments under the compact grid: at most this many (TV-safe), best first. */
export const COMPACT_COMMENTS = 3;

function CategoryCard({ category }: { category: WallCategory }) {
  const count = category.winners.length;
  const compact = count > 3;
  const commented = category.winners.filter((w) => w.comment);
  const any = commented.length > 0;
  return (
    <div className="wall-cat" data-testid="wall-category" data-category={category.id}>
      <div className="wall-cat-head">
        <span className="wall-cat-emoji" aria-hidden="true">
          {category.emoji}
        </span>
        <h2 className="wall-cat-title">{category.title}</h2>
        <p className="wall-cat-line">{category.line}</p>
      </div>
      <div className="wall-cat-side" data-verdict={any ? '' : undefined}>
        <div
          className="wall-cat-winners"
          data-count={count}
          data-compact={compact ? '' : undefined}
          data-verdict={any && !compact ? '' : undefined}
          data-cols={compact ? compactColumns(count) : undefined}
        >
          {category.winners.map((w, i) => (
            <WinnerPhoto
              key={w.photo.id}
              winner={w}
              index={i}
              count={count}
              compact={compact}
              align={verdictAlign(i, count)}
              manyComments={!compact && commented.length > 1}
            />
          ))}
        </div>
        {/* the compact grid has no room under a cell: the comments go under the grid with
            their place, their photos are ringed */}
        {any && compact ? (
          <div className="wall-cat-verdicts">
            {category.winners.flatMap((w, i) =>
              w.comment && commented.indexOf(w) < COMPACT_COMMENTS
                ? [
                    <Verdict
                      key={w.photo.id}
                      comment={w.comment}
                      place={commented.length > 1 ? i + 1 : undefined}
                    />,
                  ]
                : [],
            )}
          </div>
        ) : null}
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

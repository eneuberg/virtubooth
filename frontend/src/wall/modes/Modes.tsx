/**
 * The three wall modes as React shells around their engines (spotlight, gallery) or
 * plain markup (categories).
 */
import { useEffect, useRef, useState, type CSSProperties } from 'react';
import type { GallerySpeed, WallCategory, WallPhoto } from '../api/types';
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

function WinnerPhoto({ winner, index }: { winner: WallCategory['winners'][number]; index: number }) {
  const [loaded, setLoaded] = useState(false);
  const { photo } = winner;
  return (
    <figure className="wall-cat-photo" data-index={index}>
      <div
        className="wall-cat-pic"
        // --a: the aspect for wall.css, which fits the pictures into the row's width
        style={{ aspectRatio: String(aspectOf(photo)), '--a': String(aspectOf(photo)) } as CSSProperties}
      >
        <img
          src={photo.urls.m}
          alt={`Foto von ${photo.author}`}
          decoding="async"
          draggable={false}
          data-loaded={loaded ? '' : undefined}
          onLoad={() => setLoaded(true)}
        />
      </div>
      <span className="wall-cat-value">{winner.label}</span>
      <figcaption className="wall-cat-by">von {photo.author}</figcaption>
    </figure>
  );
}

function CategoryCard({ category }: { category: WallCategory }) {
  return (
    <div className="wall-cat" data-testid="wall-category" data-category={category.id}>
      <div className="wall-cat-head">
        <span className="wall-cat-emoji" aria-hidden="true">
          {category.emoji}
        </span>
        <h2 className="wall-cat-title">{category.title}</h2>
        <p className="wall-cat-line">{category.line}</p>
      </div>
      <div className="wall-cat-winners" data-count={category.winners.length}>
        {category.winners.map((w, i) => (
          <WinnerPhoto key={w.photo.id} winner={w} index={i} />
        ))}
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

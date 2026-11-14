import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { ActivityIndicator, AppState, Image, Modal, Pressable, ScrollView, StyleSheet, Text, View } from 'react-native';
import Slider from '@react-native-community/slider';
import { useAudioPlayer, useAudioPlayerStatus } from 'expo-audio';
import { useVideoPlayer, VideoView } from 'expo-video';
import { useEvent } from 'expo';
import { useSelfVoicingGestures } from '../gestures/useSelfVoicingGestures';
import { useFocusScroll } from '../app/useFocusScroll';
import type { ForumOpenMediaPacket } from './protocol';
import { ForumMediaUserError } from './transport';

type Action = { id: string; label: string; run: () => void };
type Props = {
  packet: ForumOpenMediaPacket;
  selfVoicing: boolean;
  announce: (text: string) => void;
  stopSpeech: () => void;
  preparePlayback: () => Promise<unknown>;
  onPlayback: (playing: boolean) => void;
  onSave: () => Promise<void>;
  onClose: () => void;
  actionNodes?: { current: Map<string, unknown> };
  onActionFocus?: (id: string) => void;
};

function clock(seconds: number): string {
  const value = Math.max(0, Math.floor(seconds || 0));
  return `${Math.floor(value / 60)}:${String(value % 60).padStart(2, '0')}`;
}

function useForegroundPause(pause: () => void) {
  const foreground = useRef(AppState.currentState === 'active');
  useEffect(() => {
    foreground.current = AppState.currentState === 'active';
    const subscription = AppState.addEventListener('change', (state) => {
      foreground.current = state === 'active';
      if (!foreground.current) pause();
    });
    return () => subscription.remove();
  }, [pause]);
  return foreground;
}

function Actions({ actions, props, children }: { actions: Action[]; props: Props; children?: React.ReactNode }) {
  const [focus, setFocus] = useState(actions[0]?.id || '');
  const focusRef = useRef(focus);
  focusRef.current = focus;
  const focusedIndex = () => Math.max(0, actions.findIndex((action) => action.id === focusRef.current));
  const selected = focusedIndex();
  const focusIndex = (index: number) => {
    const action = actions[index];
    if (!action) return;
    focusRef.current = action.id;
    setFocus(action.id);
    props.onActionFocus?.(action.id);
    props.announce(action.label);
  };
  const gestures = useSelfVoicingGestures({
    enabled: props.selfVoicing,
    globalToggleEnabled: false,
    onDoubleTap: () => actions[focusedIndex()]?.run(),
    onDoubleTapHold: () => {},
    onSingleFingerSwipe: (direction) => {
      const delta = direction === 'up' || direction === 'left' ? -1 : 1;
      focusIndex(Math.max(0, Math.min(actions.length - 1, focusedIndex() + delta)));
    },
    onThreeFingerTap: () => props.announce(props.packet.attachment.description || props.packet.attachment.name),
    onThreeFingerSwipe: (direction) => {
      if (direction === 'up') focusIndex(0);
      else if (direction === 'down') focusIndex(actions.length - 1);
    },
    onThreeFingerTripleTap: () => {},
    onTwoFingerSwipe: (direction) => { if (direction === 'up') props.onClose(); },
    onTwoFingerTap: props.stopSpeech,
  });
  return <View {...gestures.panHandlers} style={styles.actions}>
    {children}
    {actions.map((action, index) => <Pressable key={action.id} accessibilityRole="button"
      ref={(node) => {
        if (node) props.actionNodes?.current.set(action.id, node);
        else props.actionNodes?.current.delete(action.id);
      }}
      accessibilityLabel={action.label} onPress={action.run}
      onFocus={() => { if (props.selfVoicing) focusIndex(index); }}
      style={[styles.button, props.selfVoicing && index === selected ? styles.focus : undefined]}>
      <Text style={styles.text}>{action.label}</Text>
    </Pressable>)}
  </View>;
}

function useSave(props: Props) {
  const [saving, setSaving] = useState(false);
  const pending = useRef(false);
  const mounted = useRef(true);
  useEffect(() => { mounted.current = true; return () => { mounted.current = false; }; }, []);
  const save = async () => {
    if (pending.current) return;
    pending.current = true;
    setSaving(true);
    try { await props.onSave(); }
    catch (error) { if (mounted.current) props.announce(error instanceof ForumMediaUserError ? error.message : props.packet.labels.error); }
    finally { pending.current = false; if (mounted.current) setSaving(false); }
  };
  return { save, saving };
}

function useSafePlay(props: Props, play: () => void, foreground: { current: boolean }) {
  const mounted = useRef(true);
  const pending = useRef(false);
  useEffect(() => { mounted.current = true; return () => { mounted.current = false; }; }, []);
  return async () => {
    if (pending.current || !foreground.current) return;
    pending.current = true;
    props.stopSpeech();
    try {
      await props.preparePlayback();
      if (mounted.current && foreground.current) play();
    } catch { if (mounted.current) props.announce(props.packet.labels.error); }
    finally { pending.current = false; }
  };
}

function AudioAttachment(props: Props) {
  const { packet } = props;
  const source = useMemo(() => ({ uri: packet.url, headers: { Authorization: `Bearer ${packet.token}` } }), [packet]);
  const player = useAudioPlayer(source, { updateInterval: 500, downloadFirst: false });
  const status = useAudioPlayerStatus(player);
  const pause = useCallback(() => player.pause(), [player]);
  const foreground = useForegroundPause(pause);
  const [speed, setSpeed] = useState(1);
  const [volume, setVolume] = useState(0.8);
  useEffect(() => { player.volume = 0.8; }, [player]);
  const [seekPosition, setSeekPosition] = useState<number | null>(null);
  const { save, saving } = useSave(props);
  const play = useSafePlay(props, () => player.play(), foreground);
  useEffect(() => { props.onPlayback(status.playing); }, [props.onPlayback, status.playing]);
  useEffect(() => () => { props.onPlayback(false); }, [props.onPlayback]);
  const seek = (value: number) => { void player.seekTo(Math.max(0, Math.min(status.duration || 0, value))); };
  const changeSpeed = () => {
    const rates = [0.5, 0.75, 1, 1.25, 1.5, 2];
    const next = rates[(rates.indexOf(speed) + 1) % rates.length];
    player.setPlaybackRate(next);
    setSpeed(next);
    if (props.selfVoicing) props.announce(`${packet.labels.speed}: ${next}×`);
  };
  const actions: Action[] = [
    { id: 'play', label: status.playing ? packet.labels.pause : packet.labels.play, run: () => {
      if (status.playing) player.pause();
      else { void play(); }
    } },
    { id: 'rewind', label: `${packet.labels.position} −15 s`, run: () => seek(status.currentTime - 15) },
    { id: 'forward', label: `${packet.labels.position} +15 s`, run: () => seek(status.currentTime + 15) },
    { id: 'speed', label: `${packet.labels.speed}: ${speed}×`, run: changeSpeed },
    { id: 'save', label: packet.labels.download, run: () => { void save(); } },
    { id: 'close', label: packet.labels.close, run: props.onClose },
  ];
  if (props.selfVoicing) actions.splice(4, 0, { id: 'volume', label: `${packet.labels.volume}: ${Math.round(volume * 100)}%`, run: () => {
    const next = volume >= 1 ? 0 : Math.min(1, volume + 0.25);
    player.volume = next;
    setVolume(next);
    props.announce(`${packet.labels.volume}: ${Math.round(next * 100)}%`);
  } });
  return <Actions actions={actions} props={props}>
    <Text style={styles.position}>{clock(status.currentTime)} / {clock(status.duration)}</Text>
    <Slider accessibilityLabel={packet.labels.position} minimumValue={0} maximumValue={Math.max(1, status.duration || 0)}
      value={seekPosition ?? (status.currentTime || 0)} onSlidingStart={(value) => setSeekPosition(value)}
      onValueChange={(value) => setSeekPosition(value)} onSlidingComplete={(value) => { seek(value); setSeekPosition(null); }} style={styles.slider} />
    {packet.attachment.description ? <Text style={styles.text}>{packet.attachment.description}</Text> : null}
    {saving ? <ActivityIndicator accessibilityLabel={packet.labels.download} /> : null}
    {!props.selfVoicing ? <Slider accessibilityLabel={packet.labels.volume} minimumValue={0} maximumValue={1} value={volume}
      onValueChange={(value) => { player.volume = value; setVolume(value); }} style={styles.slider} /> : null}
  </Actions>;
}

function VideoAttachment(props: Props) {
  const { packet } = props;
  const source = useMemo(() => ({ uri: packet.url, headers: { Authorization: `Bearer ${packet.token}` }, useCaching: false }), [packet]);
  const player = useVideoPlayer(source, (instance) => {
    instance.audioMixingMode = 'mixWithOthers';
    instance.timeUpdateEventInterval = 0.5;
    instance.volume = 0.8;
  });
  const { isPlaying } = useEvent(player, 'playingChange', { isPlaying: false });
  const { status: playbackStatus } = useEvent(player, 'statusChange', { status: player.status });
  const timeUpdate = useEvent(player, 'timeUpdate');
  const currentTime = timeUpdate?.currentTime ?? 0;
  const pause = useCallback(() => player.pause(), [player]);
  const foreground = useForegroundPause(pause);
  const [speed, setSpeed] = useState(1);
  const [volume, setVolume] = useState(0.8);
  const [seekPosition, setSeekPosition] = useState<number | null>(null);
  const { save, saving } = useSave(props);
  const play = useSafePlay(props, () => player.play(), foreground);
  useEffect(() => { if (isPlaying) props.stopSpeech(); props.onPlayback(isPlaying); }, [isPlaying, props.onPlayback, props.stopSpeech]);
  useEffect(() => () => { props.onPlayback(false); }, [props.onPlayback]);
  const errorAnnounced = useRef(false);
  useEffect(() => {
    if (playbackStatus !== 'error') { errorAnnounced.current = false; return; }
    props.onPlayback(false);
    if (!errorAnnounced.current) {
      errorAnnounced.current = true;
      props.announce(packet.labels.error);
    }
  }, [playbackStatus, props.onPlayback, props.announce, packet.labels.error]);
  const view = useRef<VideoView>(null);
  const [fullscreen, setFullscreen] = useState(false);
  const close = () => {
    if (fullscreen) {
      void view.current?.exitFullscreen().catch(() => props.announce(packet.labels.error));
    } else props.onClose();
  };
  const controlsProps = { ...props, onClose: close };
  const [captions, setCaptions] = useState(false);
  const actions: Action[] = [
    { id: 'play', label: isPlaying ? packet.labels.pause : packet.labels.play, run: () => {
      if (isPlaying) player.pause();
      else { void play(); }
    } },
    { id: 'rewind', label: `${packet.labels.position} −15 s`, run: () => player.seekBy(-15) },
    { id: 'forward', label: `${packet.labels.position} +15 s`, run: () => player.seekBy(15) },
    { id: 'speed', label: `${packet.labels.speed}: ${speed}×`, run: () => {
      const rates = [0.5, 0.75, 1, 1.25, 1.5, 2];
      const next = rates[(rates.indexOf(speed) + 1) % rates.length];
      player.playbackRate = next;
      setSpeed(next);
      if (props.selfVoicing) props.announce(`${packet.labels.speed}: ${next}×`);
    } },
    { id: 'fullscreen', label: packet.labels.fullscreen, run: () => {
      void view.current?.enterFullscreen().catch(() => props.announce(packet.labels.error));
    } },
    { id: 'save', label: packet.labels.download, run: () => { void save(); } },
    { id: 'close', label: packet.labels.close, run: close },
  ];
  if (props.selfVoicing) actions.splice(4, 0, { id: 'volume', label: `${packet.labels.volume}: ${Math.round(volume * 100)}%`, run: () => {
    const next = volume >= 1 ? 0 : Math.min(1, volume + 0.25);
    player.volume = next;
    setVolume(next);
    props.announce(`${packet.labels.volume}: ${Math.round(next * 100)}%`);
  } });
  if (packet.captions_url) actions.splice(actions.length - 2, 0, {
    id: 'captions', label: captions ? packet.labels.captions_off : packet.labels.captions_on, run: () => {
      const track = player.availableSubtitleTracks[0];
      if (!track) { props.announce(packet.labels.captions_error); return; }
      player.subtitleTrack = captions ? null : track;
      setCaptions(!captions);
    },
  });
  return <Actions props={controlsProps} actions={actions}>
    <VideoView ref={view} player={player} style={styles.video} nativeControls={false}
      onFullscreenEnter={() => setFullscreen(true)} onFullscreenExit={() => setFullscreen(false)}
      fullscreenOptions={{ enable: true }} accessibilityLabel={packet.attachment.description || packet.attachment.name} />
    <Text style={styles.position}>{clock(currentTime)} / {clock(player.duration)}</Text>
    <Slider accessibilityLabel={packet.labels.position} minimumValue={0} maximumValue={Math.max(1, player.duration || 0)}
      value={seekPosition ?? currentTime} onSlidingStart={(value) => setSeekPosition(value)}
      onValueChange={(value) => setSeekPosition(value)} onSlidingComplete={(value) => {
        player.currentTime = Math.max(0, Math.min(player.duration || 0, value));
        setSeekPosition(null);
      }} style={styles.slider} />
    {packet.attachment.description ? <Text style={styles.text}>{packet.attachment.description}</Text> : null}
    {playbackStatus === 'error' ? <Text style={styles.text}>{packet.labels.error}</Text> : null}
    {saving ? <ActivityIndicator accessibilityLabel={packet.labels.download} /> : null}
    {!props.selfVoicing ? <Slider accessibilityLabel={packet.labels.volume} minimumValue={0} maximumValue={1} value={volume}
      onValueChange={(value) => { player.volume = value; setVolume(value); }} style={styles.slider} /> : null}
  </Actions>;
}

function ImageOrFileAttachment(props: Props) {
  const { packet } = props;
  const [zoom, setZoom] = useState(1);
  const { save, saving } = useSave(props);
  const actions: Action[] = packet.attachment.kind === 'image' ? [
    { id: 'in', label: packet.labels.zoom_in, run: () => setZoom((value) => Math.min(4, value * 1.25)) },
    { id: 'out', label: packet.labels.zoom_out, run: () => setZoom((value) => Math.max(0.25, value * 0.8)) },
  ] : [];
  actions.push({ id: 'save', label: packet.labels.download, run: () => { void save(); } },
    { id: 'close', label: packet.labels.close, run: props.onClose });
  return <Actions props={props} actions={actions}>
    {packet.attachment.kind === 'image' ? <ScrollView horizontal style={styles.imageViewport}>
      <Image source={{ uri: packet.url, headers: { Authorization: `Bearer ${packet.token}` }, cache: 'reload' }}
        accessibilityLabel={packet.attachment.description || packet.attachment.name} accessible
        onError={() => props.announce(packet.labels.error)} resizeMode="contain" style={{ width: 320 * zoom, height: 300 * zoom }} />
    </ScrollView> : packet.attachment.description ? <Text style={styles.text}>{packet.attachment.description}</Text> : null}
    {saving ? <ActivityIndicator accessibilityLabel={packet.labels.download} /> : null}
  </Actions>;
}

export function ForumMediaModal(props: Props) {
  const [actionFocus, setActionFocus] = useState<string | null>(null);
  const actionNodes = useRef(new Map<string, unknown>());
  const scroll = useFocusScroll(props.selfVoicing ? actionFocus : null, actionNodes);
  const mediaProps = { ...props, actionNodes, onActionFocus: setActionFocus };
  return <Modal visible animationType="none" onRequestClose={props.onClose} onShow={() => {
    if (props.selfVoicing) props.announce(props.packet.attachment.description || props.packet.attachment.name);
  }}>
    <View accessibilityViewIsModal style={styles.screen}>
      <Text accessibilityRole="header" style={styles.heading}>{props.packet.attachment.name}</Text>
      <ScrollView {...scroll} contentContainerStyle={styles.content}>
        {props.packet.attachment.kind === 'audio' ? <AudioAttachment {...mediaProps} />
          : props.packet.attachment.kind === 'video' ? <VideoAttachment {...mediaProps} /> : <ImageOrFileAttachment {...mediaProps} />}
      </ScrollView>
    </View>
  </Modal>;
}

const styles = StyleSheet.create({
  screen: { flex: 1, backgroundColor: '#141c28', paddingTop: 40, paddingHorizontal: 16, paddingBottom: 24 },
  content: { paddingVertical: 16, gap: 12 }, heading: { color: '#fff', fontSize: 22, fontWeight: 'bold' },
  text: { color: '#fff', fontSize: 18 }, position: { color: '#fff', fontSize: 18, textAlign: 'center' },
  actions: { gap: 10 }, button: { minHeight: 48, padding: 12, backgroundColor: '#29364a', borderWidth: 2, borderColor: 'transparent', borderRadius: 6 },
  focus: { borderColor: '#fff' }, slider: { width: '100%', height: 48 }, video: { width: '100%', height: 260 },
  imageViewport: { minHeight: 300 },
});

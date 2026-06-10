import {
  afterPatch,
  fakeRenderComponent,
  findInReactTree,
  findModuleByExport,
  findInTree,
  Export,
  MenuItem,
  Navigation,
  Patch,
} from '@decky/ui';
import { FC } from 'react';

const spliceConfigureModsItem = (children: any[], appid: number) => {
  const propertiesMenuItemIdx = children.findIndex((item) =>
    findInReactTree(item, (x) => x?.onSelected && x.onSelected.toString().includes('AppProperties'))
  );

  // Only insert when Properties is reachable from the menu's tree. The top-level
  // app context menu nests Properties inside the Manage trigger; the Manage
  // submenu (and other submenus) don't expose Properties at all, so we skip.
  // The upstream launchSource check is leaky — Uninstall's onSelected also
  // references launchSource, which is why the Manage submenu sneaks past it.
  if (propertiesMenuItemIdx === -1) return;

  children.splice(propertiesMenuItemIdx, 0, (
    <MenuItem
      key="moddy-configure-mods"
      onSelected={() => {
        Navigation.Navigate(`/moddy/${appid}`);
      }}
    >
      Configure Mods...
    </MenuItem>
  ));
};

const isOpeningAppContextMenu = (items: any[]) => {
  if (!items?.length) return false;
  return !!findInReactTree(items, (x) => x?.props?.onSelected && x?.props?.onSelected.toString().includes('launchSource'));
};

const handleItemDupes = (items: any[]) => {
  const idx = items.findIndex((x: any) => x?.key === 'moddy-configure-mods');
  if (idx !== -1) items.splice(idx, 1);
};

const patchMenuItems = (menuItems: any[], appid: number, supportedAppIds: Set<number>) => {
  let updatedAppid: number = appid;
  const parentOverview = menuItems.find((x: any) => x?._owner?.pendingProps?.overview?.appid &&
    x._owner.pendingProps.overview.appid !== appid
  );
  if (parentOverview) {
    updatedAppid = parentOverview._owner.pendingProps.overview.appid;
  }
  if (updatedAppid === appid) {
    const foundApp = findInTree(menuItems, (x) => x?.app?.appid, { walkable: ['props', 'children'] });
    if (foundApp) {
      updatedAppid = foundApp.app.appid;
    }
  }
  if (!supportedAppIds.has(updatedAppid)) return;
  spliceConfigureModsItem(menuItems, updatedAppid);
};

const contextMenuPatch = (LibraryContextMenu: any, supportedAppIds: Set<number>) => {
  const patches: {
    outer?: Patch,
    inner?: Patch,
    unpatch: () => void;
  } = { unpatch: () => { return null; } };

  patches.outer = afterPatch(LibraryContextMenu.prototype, 'render', (_: Record<string, unknown>[], component: any) => {
    let appid: number = 0;
    if (component._owner) {
      appid = component._owner.pendingProps.overview.appid;
    } else {
      const foundApp = findInTree(component.props.children, (x) => x?.app?.appid, { walkable: ['props', 'children'] });
      if (foundApp) {
        appid = foundApp.app.appid;
      }
    }

    if (!patches.inner) {
      patches.inner = afterPatch(component, 'type', (_: any, ret: any) => {
        afterPatch(ret.type.prototype, 'render', (_: any, ret2: any) => {
          const menuItems = ret2.props.children[0];
          if (!isOpeningAppContextMenu(menuItems)) return ret2;
          try { handleItemDupes(menuItems); } catch { return ret2; }
          patchMenuItems(menuItems, appid, supportedAppIds);
          return ret2;
        });

        afterPatch(ret.type.prototype, 'shouldComponentUpdate', ([nextProps]: any, shouldUpdate: any) => {
          try { handleItemDupes(nextProps.children); } catch { return shouldUpdate; }
          if (shouldUpdate === true) {
            patchMenuItems(nextProps.children, appid, supportedAppIds);
          }
          return shouldUpdate;
        });
        return ret;
      });
    }
    return component;
  });

  patches.unpatch = () => {
    patches.outer?.unpatch();
    patches.inner?.unpatch();
  };
  return patches;
};

export const LibraryContextMenu = fakeRenderComponent(
  Object.values(
    findModuleByExport((e: Export) => e?.toString && e.toString().includes('().LibraryContextMenu'))
  ).find((sibling) => (
    sibling?.toString().includes('navigator:')
  )) as FC
).type;

export default contextMenuPatch;
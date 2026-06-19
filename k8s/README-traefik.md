# Traefik Ingress + Basic Auth for VM-Tips

## Prerequisites
- Traefik Ingress Controller installed in your cluster (you said you use it).
- DNS for `vm.blodsnigel.se` pointing to your Traefik entrypoint (LoadBalancer IP, NodePort, or whatever you expose).
- kubectl access.

## 1. Create the Basic Auth Secret

Run this locally (choose your own username and password; you can add multiple users):

```bash
# Example for one user (replace username and password)
echo "lillen:$(openssl passwd -apr1 'dittlosenordhär')" | kubectl create secret generic vmtips-basic-auth --from-file=auth=/dev/stdin --namespace default

# For multiple users (e.g. Lillen and Stinis):
echo -e "lillen:$(openssl passwd -apr1 'lillenslosenord')\nstinis:$(openssl passwd -apr1 'stinislosenord')" | kubectl create secret generic vmtips-basic-auth --from-file=auth=/dev/stdin --namespace default
```

Verify:
```bash
kubectl get secret vmtips-basic-auth -n default
kubectl get secret vmtips-basic-auth -n default -o yaml
```

## 2. Apply Middleware and Ingress

```bash
kubectl apply -f k8s/middleware-basic-auth.yaml
kubectl apply -f k8s/ingress.yaml
```

## 3. Verify

```bash
kubectl get ingress vmtips -n default
kubectl get middleware vmtips-basic-auth -n default
```

Check logs:
```bash
kubectl logs -l app=traefik -n traefik  # adjust namespace if different
```

## 4. Test

Open https://vm.blodsnigel.se (or http if no TLS yet).

You should get a browser Basic Auth prompt.

Username: lillen (or whatever you chose)
Password: the one you set.

## Notes

- The Ingress uses Traefik annotations.
- For HTTPS, add a cert (cert-manager + Let's Encrypt or manual) and uncomment the websecure lines in ingress.yaml. Then update the middleware annotation if needed.
- If your Traefik is in another namespace, adjust the middleware reference: `yourtraefikns-vmtips-basic-auth@kubernetescrd`
- The service `vmtips` on port 80 must exist (it's defined in deployment.yaml).
- After changes: `kubectl rollout restart deployment/vmtips`

## If you delete the PVC for a fresh start

```bash
kubectl scale deploy vmtips --replicas=0
kubectl delete pvc vmtips-data
kubectl apply -f k8s/pvc.yaml
kubectl scale deploy vmtips --replicas=1
```

Then re-apply ingress/middleware if needed.

## Re-import your bets after reset

See main README or run the reimport script as before.

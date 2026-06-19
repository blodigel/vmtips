# Traefik Ingress + Basic Auth for VM-Tips

## Prerequisites
- Traefik Ingress Controller installed in your cluster (you said you use it).
- DNS for `vm.blodsnigel.se` pointing to your Traefik entrypoint (LoadBalancer IP, NodePort, or whatever you expose).
- kubectl access.

## 1. Create the Basic Auth Secret

The secret must contain a file called `auth` with htpasswd-formatted lines.

### Recommended way (interactive, most reliable):

```bash
# Create htpasswd file (you will be prompted for password)
htpasswd -c auth lillen

# If you want to add Stinis too:
htpasswd auth stinis

# Create the secret from the file
kubectl create secret generic vmtips-basic-auth \
  --from-file=auth=auth \
  --namespace default

# Clean up the local file
rm auth
```

### Alternative one-liner (if you don't have htpasswd installed):

```bash
echo "lillen:$(openssl passwd -apr1 'YOUR_PASSWORD_HERE')" | \
  kubectl create secret generic vmtips-basic-auth \
  --from-file=auth=/dev/stdin \
  --namespace default
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

Check Traefik logs (adjust namespace if your Traefik is not in `traefik`):
```bash
kubectl logs -l app=traefik -n traefik --tail=50
```

## 4. Test

Once your DNS for `vm.blodsnigel.se` is pointing to your Traefik (LoadBalancer/NodePort/etc.), open the URL in the browser.

You should get a Basic Auth prompt.

Username + password = whatever you put in the secret.

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
